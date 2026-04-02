"""Multi-line text editor with autocomplete, paste handling, and vertical scrolling."""
from __future__ import annotations

import re
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

import grapheme

from pana.tui.ansi import ANSI
from pana.tui.keybindings import get_editor_keybindings
from pana.tui.keys import decode_kitty_printable, matches_key
from pana.tui.kill_ring import KillRing
from pana.tui.undo_stack import UndoStack
from pana.tui.utils import is_punctuation_char, is_whitespace_char, visible_width

if TYPE_CHECKING:
    from pana.tui.autocomplete import AutocompleteProvider
    from pana.tui.tui import TUI


@dataclass
class SelectListTheme:
    selected_prefix: Callable[[str], str]
    selected_text: Callable[[str], str]
    description: Callable[[str], str]
    scroll_info: Callable[[str], str]
    no_match: Callable[[str], str]


@dataclass
class EditorTheme:
    border_color: Callable[[str], str]
    select_list: SelectListTheme


@dataclass
class EditorOptions:
    padding_x: int = 0
    autocomplete_max_visible: int = 5


def _graphemes(text: str) -> list[str]:
    return list(grapheme.graphemes(text))


# Paste marker patterns
_PASTE_MARKER_REGEX = re.compile(r"\[paste #(\d+)( (\+\d+ lines|\d+ chars))?\]")
_PASTE_MARKER_SINGLE = re.compile(r"^\[paste #(\d+)( (\+\d+ lines|\d+ chars))?\]$")


def _is_paste_marker(segment: str) -> bool:
    """Check if a string is a paste marker."""
    return len(segment) >= 10 and _PASTE_MARKER_SINGLE.match(segment) is not None


def _segment_with_markers(text: str, valid_ids: set[int]) -> list[dict]:
    """Segment text with paste-marker awareness.

    Merges graphemes within paste markers (with valid IDs) into single
    atomic segments so that cursor movement, deletion, word-wrap, etc.
    treat paste markers as single units.

    Returns a list of dicts with keys 'segment' and 'index', mimicking
    the Intl.Segmenter interface from the original TS implementation.
    """
    if not valid_ids or "[paste #" not in text:
        return [{"segment": g, "index": i}
                for i, g in _graphemes_with_indices(text)]

    # Find all marker spans with valid IDs
    markers: list[tuple[int, int]] = []
    for m in _PASTE_MARKER_REGEX.finditer(text):
        pid = int(m.group(1))
        if pid in valid_ids:
            markers.append((m.start(), m.end()))

    if not markers:
        return [{"segment": g, "index": i}
                for i, g in _graphemes_with_indices(text)]

    # Build merged segment list
    base_segments = list(_graphemes_with_indices(text))
    result: list[dict] = []
    marker_idx = 0

    for char_idx, g in base_segments:
        # Skip past markers entirely before this segment
        while marker_idx < len(markers) and markers[marker_idx][1] <= char_idx:
            marker_idx += 1

        marker = markers[marker_idx] if marker_idx < len(markers) else None
        if marker and char_idx >= marker[0] and char_idx < marker[1]:
            # This segment falls inside a marker
            if char_idx == marker[0]:
                # First segment of marker: emit merged segment
                marker_text = text[marker[0]:marker[1]]
                result.append({"segment": marker_text, "index": marker[0]})
            # Otherwise skip (already merged)
        else:
            result.append({"segment": g, "index": char_idx})

    return result


def _graphemes_with_indices(text: str) -> list[tuple[int, int]]:
    """Return list of (char_index, grapheme_str) pairs."""
    result: list[tuple[int, str]] = []
    pos = 0
    for g in grapheme.graphemes(text):
        result.append((pos, g))
        pos += len(g)
    return result


def word_wrap_line(
    line: str,
    max_width: int,
    pre_segmented: list[dict] | None = None,
) -> list[dict]:
    """Split a line into word-wrapped chunks.

    Args:
        line: The text line to wrap
        max_width: Maximum visible width per chunk
        pre_segmented: Optional pre-segmented list of dicts with 'segment' and
                       'index' keys (e.g. with paste-marker awareness).
                       When omitted, the default grapheme segmenter is used.
    """
    if not line or max_width <= 0:
        return [{"text": "", "start_index": 0, "end_index": 0}]
    lw = visible_width(line)
    if lw <= max_width:
        return [{"text": line, "start_index": 0, "end_index": len(line)}]

    chunks: list[dict] = []

    if pre_segmented is not None:
        segs = [s["segment"] for s in pre_segmented]
        char_indices = [s["index"] for s in pre_segmented]
    else:
        segs = list(grapheme.graphemes(line))
        char_indices = []
        pos = 0
        for seg in segs:
            char_indices.append(pos)
            pos += len(seg)

    current_width = 0
    chunk_start = 0
    wrap_opp_index = -1
    wrap_opp_width = 0

    for i, seg in enumerate(segs):
        g_width = visible_width(seg)
        char_idx = char_indices[i]
        is_ws = is_whitespace_char(seg)

        if current_width + g_width > max_width:
            if wrap_opp_index >= 0:
                chunks.append({
                    "text": line[chunk_start:wrap_opp_index],
                    "start_index": chunk_start,
                    "end_index": wrap_opp_index,
                })
                chunk_start = wrap_opp_index
                current_width -= wrap_opp_width
            elif chunk_start < char_idx:
                chunks.append({
                    "text": line[chunk_start:char_idx],
                    "start_index": chunk_start,
                    "end_index": char_idx,
                })
                chunk_start = char_idx
                current_width = 0
            wrap_opp_index = -1

        current_width += g_width

        if is_ws and i + 1 < len(segs) and not is_whitespace_char(segs[i + 1]):
            next_char_idx = char_indices[i + 1]
            wrap_opp_index = next_char_idx
            wrap_opp_width = current_width

    chunks.append({
        "text": line[chunk_start:],
        "start_index": chunk_start,
        "end_index": len(line),
    })
    return chunks


class Editor:
    def __init__(self, tui: TUI, theme: EditorTheme, options: EditorOptions | None = None) -> None:
        opts = options or EditorOptions()
        self._tui = tui
        self._theme = theme
        self._lines: list[str] = [""]
        self._cursor_line = 0
        self._cursor_col = 0
        self._last_width = 80
        self._scroll_offset = 0
        self.border_color = theme.border_color
        self.focused: bool = False

        self._padding_x = max(0, opts.padding_x)
        self._autocomplete_max_visible = max(3, min(20, opts.autocomplete_max_visible))
        self._autocomplete_provider: AutocompleteProvider | None = None
        self._autocomplete_list: Any = None
        self._autocomplete_state: str | None = None  # "regular" | "force" | None
        self._autocomplete_prefix = ""

        self._pastes: dict[int, str] = {}
        self._paste_counter = 0
        self._paste_buffer = ""
        self._is_in_paste = False

        self._history: list[str] = []
        self._history_index = -1

        self._kill_ring = KillRing()
        self._last_action: str | None = None
        self._jump_mode: str | None = None
        self._preferred_visual_col: int | None = None
        self._undo_stack: UndoStack[dict] = UndoStack()

        self.on_submit: Callable[[str], Awaitable[None]] | None = None
        self.on_change: Callable[[str], None] | None = None
        self.on_action: Callable[[str], None] | None = None
        self.disable_submit = False

    @property
    def _valid_paste_ids(self) -> set[int]:
        """Set of currently valid paste IDs, for marker-aware segmentation."""
        return set(self._pastes.keys())

    def _segment(self, text: str) -> list[dict]:
        """Segment text with paste-marker awareness, only merging markers with valid IDs."""
        return _segment_with_markers(text, self._valid_paste_ids)

    def get_padding_x(self) -> int:
        return self._padding_x

    def set_padding_x(self, padding: int) -> None:
        self._padding_x = max(0, padding)
        self._tui.request_render()

    def set_autocomplete_provider(self, provider: AutocompleteProvider) -> None:
        self._autocomplete_provider = provider

    def set_autocomplete_max_visible(self, max_visible: int) -> None:
        self._autocomplete_max_visible = max(3, min(20, max_visible))

    def add_to_history(self, text: str) -> None:
        trimmed = text.strip()
        if not trimmed:
            return
        if self._history and self._history[0] == trimmed:
            return
        self._history.insert(0, trimmed)
        if len(self._history) > 100:
            self._history.pop()

    def invalidate(self) -> None:
        pass

    def get_text(self) -> str:
        return "\n".join(self._lines)

    def get_expanded_text(self) -> str:
        result = self.get_text()
        for pid, content in self._pastes.items():
            result = re.sub(rf"\[paste #{pid}( (\+\d+ lines|\d+ chars))?\]", content, result)
        return result

    def get_lines(self) -> list[str]:
        return list(self._lines)

    def get_cursor(self) -> dict:
        return {"line": self._cursor_line, "col": self._cursor_col}

    def set_text(self, text: str) -> None:
        self._last_action = None
        self._history_index = -1
        if self.get_text() != text:
            self._push_undo()
        self._set_text_internal(text)

    def insert_text_at_cursor(self, text: str) -> None:
        if not text:
            return
        self._push_undo()
        self._last_action = None
        self._history_index = -1
        self._insert_text_internal(text)


    def render(self, width: int) -> list[str]:
        max_pad = max(0, (width - 1) // 2)
        px = min(self._padding_x, max_pad)
        content_width = max(1, width - px * 2)
        layout_width = max(1, content_width - (0 if px else 1))
        self._last_width = layout_width

        horizontal = self.border_color("─")
        layout_lines = self._layout_text(layout_width)

        term_rows = self._tui.terminal.rows
        max_visible = max(5, term_rows * 3 // 10)

        cursor_line_idx = next(
            (i for i, ll in enumerate(layout_lines) if ll["has_cursor"]), 0
        )

        if cursor_line_idx < self._scroll_offset:
            self._scroll_offset = cursor_line_idx
        elif cursor_line_idx >= self._scroll_offset + max_visible:
            self._scroll_offset = cursor_line_idx - max_visible + 1
        max_scroll = max(0, len(layout_lines) - max_visible)
        self._scroll_offset = max(0, min(self._scroll_offset, max_scroll))

        visible = layout_lines[self._scroll_offset : self._scroll_offset + max_visible]

        result: list[str] = []
        left_pad = " " * px
        right_pad = left_pad
        emit_marker = self.focused and not self._autocomplete_state

        # Top border
        if self._scroll_offset > 0:
            indicator = f"─── ↑ {self._scroll_offset} more "
            remaining = width - visible_width(indicator)
            result.append(self.border_color(indicator + "─" * max(0, remaining)))
        else:
            result.append(horizontal * width)

        for ll in visible:
            display = ll["text"]
            line_vw = visible_width(ll["text"])
            cursor_in_pad = False

            if ll["has_cursor"] and ll.get("cursor_pos") is not None:
                cp = ll["cursor_pos"]
                before = display[:cp]
                after = display[cp:]
                marker = ANSI.CURSOR_MARKER if emit_marker else ""

                if after:
                    gs = _graphemes(after)
                    first_g = gs[0] if gs else ""
                    rest = after[len(first_g):]
                    cursor_ch = f"{ANSI.INVERSE_ON}{first_g}{ANSI.RESET}"
                    display = before + marker + cursor_ch + rest
                else:
                    cursor_ch = f"{ANSI.INVERSE_ON} {ANSI.RESET}"
                    display = before + marker + cursor_ch
                    line_vw += 1
                    if line_vw > content_width and px > 0:
                        cursor_in_pad = True

            padding = " " * max(0, content_width - line_vw)
            rp = right_pad[1:] if cursor_in_pad else right_pad
            result.append(f"{left_pad}{display}{padding}{rp}")

        # Bottom border
        lines_below = len(layout_lines) - (self._scroll_offset + len(visible))
        if lines_below > 0:
            indicator = f"─── ↓ {lines_below} more "
            remaining = width - visible_width(indicator)
            result.append(self.border_color(indicator + "─" * max(0, remaining)))
        else:
            result.append(horizontal * width)

        # Autocomplete
        if self._autocomplete_state and self._autocomplete_list:
            for line in self._autocomplete_list.render(content_width):
                lw = visible_width(line)
                lp = " " * max(0, content_width - lw)
                result.append(f"{left_pad}{line}{lp}{right_pad}")

        return result

    def _layout_text(self, content_width: int) -> list[dict]:
        layout: list[dict] = []
        if not self._lines or (len(self._lines) == 1 and self._lines[0] == ""):
            layout.append({"text": "", "has_cursor": True, "cursor_pos": 0})
            return layout

        for i, line in enumerate(self._lines):
            is_current = i == self._cursor_line
            if visible_width(line) <= content_width:
                layout.append({
                    "text": line,
                    "has_cursor": is_current,
                    "cursor_pos": self._cursor_col if is_current else None,
                })
            else:
                pre_seg = self._segment(line) if self._pastes else None
                chunks = word_wrap_line(line, content_width, pre_segmented=pre_seg)
                for ci, chunk in enumerate(chunks):
                    has_cursor = False
                    adj_pos = None
                    if is_current:
                        is_last = ci == len(chunks) - 1
                        if is_last:
                            if self._cursor_col >= chunk["start_index"]:
                                has_cursor = True
                                adj_pos = self._cursor_col - chunk["start_index"]
                        else:
                            if chunk["start_index"] <= self._cursor_col < chunk["end_index"]:
                                has_cursor = True
                                adj_pos = min(
                                    self._cursor_col - chunk["start_index"],
                                    len(chunk["text"]),
                                )
                    layout.append({
                        "text": chunk["text"],
                        "has_cursor": has_cursor,
                        "cursor_pos": adj_pos,
                    })
        return layout


    async def handle_input(self, data: str) -> None:
        kb = get_editor_keybindings()

        # App-level actions — dispatched before any editor handling
        if self.on_action:
            for action_id in kb.get_app_actions():
                if kb.matches(data, action_id):
                    self.on_action(action_id)
                    return

        # Jump mode
        if self._jump_mode is not None:
            if kb.matches(data, "tui.editor.jumpForward") or kb.matches(data, "tui.editor.jumpBackward"):
                self._jump_mode = None
                return
            if ord(data[0]) >= 32 if data else False:
                direction = self._jump_mode
                self._jump_mode = None
                self._jump_to_char(data, direction)
                return
            self._jump_mode = None

        # Bracketed paste
        if ANSI.PASTE_START in data:
            self._is_in_paste = True
            self._paste_buffer = ""
            data = data.replace(ANSI.PASTE_START, "")
        if self._is_in_paste:
            self._paste_buffer += data
            end_idx = self._paste_buffer.find(ANSI.PASTE_END)
            if end_idx != -1:
                paste_content = self._paste_buffer[:end_idx]
                if paste_content:
                    self._handle_paste(paste_content)
                self._is_in_paste = False
                remaining = self._paste_buffer[end_idx + 6:]
                self._paste_buffer = ""
                if remaining:
                    await self.handle_input(remaining)
            return

        if kb.matches(data, "tui.input.copy"):
            return
        if kb.matches(data, "tui.editor.undo"):
            self._undo()
            return

        # Autocomplete mode
        if self._autocomplete_state and self._autocomplete_list:
            if kb.matches(data, "tui.select.cancel"):
                self._cancel_autocomplete()
                return
            if kb.matches(data, "tui.select.up") or kb.matches(data, "tui.select.down"):
                await self._autocomplete_list.handle_input(data)
                return
            if kb.matches(data, "tui.input.tab"):
                sel = self._autocomplete_list.get_selected_item()
                if sel and self._autocomplete_provider:
                    should_chain = self._should_chain_slash_autocomplete_on_tab()
                    self._push_undo()
                    self._last_action = None
                    r = self._autocomplete_provider.apply_completion(
                        self._lines, self._cursor_line, self._cursor_col,
                        sel, self._autocomplete_prefix,
                    )
                    self._lines = r["lines"]
                    self._cursor_line = r["cursor_line"]
                    self._set_cursor_col(r["cursor_col"])
                    self._cancel_autocomplete()
                    if self.on_change:
                        self.on_change(self.get_text())
                    # Chain into argument completions for slash commands
                    if should_chain and self._is_bare_completed_slash_at_cursor():
                        self._try_trigger_autocomplete()
                return
            if kb.matches(data, "tui.select.confirm"):
                sel = self._autocomplete_list.get_selected_item()
                if sel and self._autocomplete_provider:
                    self._push_undo()
                    self._last_action = None
                    r = self._autocomplete_provider.apply_completion(
                        self._lines, self._cursor_line, self._cursor_col,
                        sel, self._autocomplete_prefix,
                    )
                    self._lines = r["lines"]
                    self._cursor_line = r["cursor_line"]
                    self._set_cursor_col(r["cursor_col"])
                    if self._autocomplete_prefix.startswith("/"):
                        self._cancel_autocomplete()
                    else:
                        self._cancel_autocomplete()
                        if self.on_change:
                            self.on_change(self.get_text())
                        return

        if kb.matches(data, "tui.input.tab") and not self._autocomplete_state:
            self._handle_tab()
            return

        # Deletion
        if kb.matches(data, "tui.editor.deleteToLineEnd"):
            self._delete_to_end()
            return
        if kb.matches(data, "tui.editor.deleteToLineStart"):
            self._delete_to_start()
            return
        if kb.matches(data, "tui.editor.deleteWordBackward"):
            self._delete_word_backward()
            return
        if kb.matches(data, "tui.editor.deleteWordForward"):
            self._delete_word_forward()
            return
        if kb.matches(data, "tui.editor.deleteCharBackward") or matches_key(data, "shift+backspace"):
            self._handle_backspace()
            return
        if kb.matches(data, "tui.editor.deleteCharForward") or matches_key(data, "shift+delete"):
            self._handle_forward_delete()
            return

        # Kill ring
        if kb.matches(data, "tui.editor.yank"):
            self._yank()
            return
        if kb.matches(data, "tui.editor.yankPop"):
            self._yank_pop()
            return

        # Cursor movement
        if kb.matches(data, "tui.editor.cursorLineStart"):
            self._last_action = None
            self._set_cursor_col(0)
            return
        if kb.matches(data, "tui.editor.cursorLineEnd"):
            self._last_action = None
            self._set_cursor_col(len(self._lines[self._cursor_line]))
            return
        if kb.matches(data, "tui.editor.cursorWordLeft"):
            self._move_word_backward()
            return
        if kb.matches(data, "tui.editor.cursorWordRight"):
            self._move_word_forward()
            return

        # New line
        if (
            kb.matches(data, "tui.input.newLine")
            or (len(data) > 1 and ord(data[0]) == 10)
            or data == "\x1b\r"
            or data == "\x1b[13;2~"
            or (data == "\n" and len(data) == 1)
        ):
            if self._should_submit_on_backslash_enter(data, kb):
                self._handle_backspace()
                await self._submit()
                return
            self._add_new_line()
            return

        # Submit
        if kb.matches(data, "tui.input.submit"):
            if self.disable_submit:
                return
            current = self._lines[self._cursor_line]
            if self._cursor_col > 0 and current[self._cursor_col - 1:self._cursor_col] == "\\":
                self._handle_backspace()
                self._add_new_line()
                return
            await self._submit()
            return

        # Arrow keys with history
        if kb.matches(data, "tui.editor.cursorUp"):
            if self._is_empty():
                self._navigate_history(-1)
            elif self._history_index > -1 and self._on_first_visual_line():
                self._navigate_history(-1)
            elif self._on_first_visual_line():
                self._set_cursor_col(0)
            else:
                self._move_cursor(-1, 0)
            return
        if kb.matches(data, "tui.editor.cursorDown"):
            if self._history_index > -1 and self._on_last_visual_line():
                self._navigate_history(1)
            elif self._on_last_visual_line():
                self._set_cursor_col(len(self._lines[self._cursor_line]))
            else:
                self._move_cursor(1, 0)
            return
        if kb.matches(data, "tui.editor.cursorRight"):
            self._move_cursor(0, 1)
            return
        if kb.matches(data, "tui.editor.cursorLeft"):
            self._move_cursor(0, -1)
            return

        if kb.matches(data, "tui.editor.pageUp"):
            self._page_scroll(-1)
            return
        if kb.matches(data, "tui.editor.pageDown"):
            self._page_scroll(1)
            return

        if kb.matches(data, "tui.editor.jumpForward"):
            self._jump_mode = "forward"
            return
        if kb.matches(data, "tui.editor.jumpBackward"):
            self._jump_mode = "backward"
            return

        if matches_key(data, "shift+space"):
            self._insert_char(" ")
            return

        kp = decode_kitty_printable(data)
        if kp is not None:
            self._insert_char(kp)
            return

        if data and ord(data[0]) >= 32:
            self._insert_char(data)


    def _set_cursor_col(self, col: int) -> None:
        self._cursor_col = col
        self._preferred_visual_col = None

    def _push_undo(self) -> None:
        self._undo_stack.push({
            "lines": list(self._lines),
            "cursor_line": self._cursor_line,
            "cursor_col": self._cursor_col,
        })

    def _undo(self) -> None:
        self._history_index = -1
        snap = self._undo_stack.pop()
        if not snap:
            return
        self._lines = snap["lines"]
        self._cursor_line = snap["cursor_line"]
        self._cursor_col = snap["cursor_col"]
        self._last_action = None
        self._preferred_visual_col = None
        if self.on_change:
            self.on_change(self.get_text())

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize text for editor storage.

        - Normalize line endings (\\r\\n and \\r -> \\n)
        - Expand tabs to 4 spaces
        """
        return text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")

    def _set_text_internal(self, text: str) -> None:
        normalized = self._normalize_text(text)
        lines = normalized.split("\n")
        self._lines = lines if lines else [""]
        self._cursor_line = len(self._lines) - 1
        self._set_cursor_col(len(self._lines[self._cursor_line]))
        self._scroll_offset = 0
        if self.on_change:
            self.on_change(self.get_text())

    def _insert_text_internal(self, text: str) -> None:
        normalized = self._normalize_text(text)
        inserted = normalized.split("\n")
        current = self._lines[self._cursor_line]
        before = current[:self._cursor_col]
        after = current[self._cursor_col:]

        if len(inserted) == 1:
            self._lines[self._cursor_line] = before + normalized + after
            self._set_cursor_col(self._cursor_col + len(normalized))
        else:
            new_lines = (
                self._lines[:self._cursor_line]
                + [before + inserted[0]]
                + inserted[1:-1]
                + [inserted[-1] + after]
                + self._lines[self._cursor_line + 1:]
            )
            self._lines = new_lines
            self._cursor_line += len(inserted) - 1
            self._set_cursor_col(len(inserted[-1]))

        if self.on_change:
            self.on_change(self.get_text())

    def _insert_char(self, char: str) -> None:
        self._history_index = -1
        if is_whitespace_char(char) or self._last_action != "type-word":
            self._push_undo()
        self._last_action = "type-word"

        line = self._lines[self._cursor_line]
        self._lines[self._cursor_line] = line[:self._cursor_col] + char + line[self._cursor_col:]
        self._set_cursor_col(self._cursor_col + len(char))

        if self.on_change:
            self.on_change(self.get_text())

        # Autocomplete triggers
        if not self._autocomplete_state:
            if char == "/" and self._is_at_start():
                self._try_trigger_autocomplete()
            elif char == "@":
                cur = self._lines[self._cursor_line]
                before_at = cur[:self._cursor_col]
                ch_before = before_at[-2] if len(before_at) >= 2 else ""
                if len(before_at) == 1 or ch_before in (" ", "\t"):
                    self._try_trigger_autocomplete()
            elif re.match(r"[a-zA-Z0-9.\-_]", char):
                cur = self._lines[self._cursor_line]
                before = cur[:self._cursor_col]
                if self._is_in_slash_context(before):
                    self._try_trigger_autocomplete()
                elif re.search(r"(?:^|[\s])@[^\s]*$", before):
                    self._try_trigger_autocomplete()
        else:
            self._update_autocomplete()

    def _handle_paste(self, pasted: str) -> None:
        self._history_index = -1
        self._last_action = None
        self._push_undo()
        clean = pasted.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
        filtered = "".join(ch for ch in clean if ch == "\n" or ord(ch) >= 32)

        pasted_lines = filtered.split("\n")
        if len(pasted_lines) > 10 or len(filtered) > 1000:
            self._paste_counter += 1
            pid = self._paste_counter
            self._pastes[pid] = filtered
            marker = (
                f"[paste #{pid} +{len(pasted_lines)} lines]"
                if len(pasted_lines) > 10
                else f"[paste #{pid} {len(filtered)} chars]"
            )
            self._insert_text_internal(marker)
            return

        self._insert_text_internal(filtered)

    def _add_new_line(self) -> None:
        self._history_index = -1
        self._last_action = None
        self._push_undo()
        current = self._lines[self._cursor_line]
        before = current[:self._cursor_col]
        after = current[self._cursor_col:]
        self._lines[self._cursor_line] = before
        self._lines.insert(self._cursor_line + 1, after)
        self._cursor_line += 1
        self._set_cursor_col(0)
        if self.on_change:
            self.on_change(self.get_text())

    async def _submit(self) -> None:
        result = "\n".join(self._lines).strip()
        for pid, content in self._pastes.items():
            result = re.sub(rf"\[paste #{pid}( (\+\d+ lines|\d+ chars))?\]", content, result)
        self._lines = [""]
        self._cursor_line = 0
        self._cursor_col = 0
        self._pastes.clear()
        self._paste_counter = 0
        self._history_index = -1
        self._scroll_offset = 0
        self._undo_stack.clear()
        self._last_action = None
        if self.on_change:
            self.on_change("")
        if self.on_submit:
            await self.on_submit(result)

    def _handle_backspace(self) -> None:
        self._history_index = -1
        self._last_action = None
        if self._cursor_col > 0:
            self._push_undo()
            line = self._lines[self._cursor_line]
            before = line[:self._cursor_col]
            gs = _graphemes(before)
            last_g = gs[-1] if gs else ""
            gl = len(last_g) if last_g else 1
            self._lines[self._cursor_line] = line[:self._cursor_col - gl] + line[self._cursor_col:]
            self._set_cursor_col(self._cursor_col - gl)
        elif self._cursor_line > 0:
            self._push_undo()
            current = self._lines[self._cursor_line]
            prev = self._lines[self._cursor_line - 1]
            self._lines[self._cursor_line - 1] = prev + current
            del self._lines[self._cursor_line]
            self._cursor_line -= 1
            self._set_cursor_col(len(prev))

        if self.on_change:
            self.on_change(self.get_text())

        if self._autocomplete_state:
            self._update_autocomplete()
        else:
            before = self._lines[self._cursor_line][:self._cursor_col]
            if self._is_in_slash_context(before) or re.search(r"(?:^|[\s])@[^\s]*$", before):
                self._try_trigger_autocomplete()

    def _handle_forward_delete(self) -> None:
        self._history_index = -1
        self._last_action = None
        line = self._lines[self._cursor_line]
        if self._cursor_col < len(line):
            self._push_undo()
            after = line[self._cursor_col:]
            gs = _graphemes(after)
            first_g = gs[0] if gs else ""
            gl = len(first_g) if first_g else 1
            self._lines[self._cursor_line] = line[:self._cursor_col] + line[self._cursor_col + gl:]
        elif self._cursor_line < len(self._lines) - 1:
            self._push_undo()
            next_line = self._lines[self._cursor_line + 1]
            self._lines[self._cursor_line] = line + next_line
            del self._lines[self._cursor_line + 1]
        if self.on_change:
            self.on_change(self.get_text())

        if self._autocomplete_state:
            self._update_autocomplete()
        else:
            before = self._lines[self._cursor_line][:self._cursor_col]
            if self._is_in_slash_context(before) or re.search(r"(?:^|[\s])@[^\s]*$", before):
                self._try_trigger_autocomplete()

    def _delete_to_start(self) -> None:
        self._history_index = -1
        line = self._lines[self._cursor_line]
        if self._cursor_col > 0:
            self._push_undo()
            deleted = line[:self._cursor_col]
            self._kill_ring.push(deleted, prepend=True, accumulate=self._last_action == "kill")
            self._last_action = "kill"
            self._lines[self._cursor_line] = line[self._cursor_col:]
            self._set_cursor_col(0)
        elif self._cursor_line > 0:
            self._push_undo()
            self._kill_ring.push("\n", prepend=True, accumulate=self._last_action == "kill")
            self._last_action = "kill"
            prev = self._lines[self._cursor_line - 1]
            self._lines[self._cursor_line - 1] = prev + line
            del self._lines[self._cursor_line]
            self._cursor_line -= 1
            self._set_cursor_col(len(prev))
        if self.on_change:
            self.on_change(self.get_text())

    def _delete_to_end(self) -> None:
        self._history_index = -1
        line = self._lines[self._cursor_line]
        if self._cursor_col < len(line):
            self._push_undo()
            deleted = line[self._cursor_col:]
            self._kill_ring.push(deleted, prepend=False, accumulate=self._last_action == "kill")
            self._last_action = "kill"
            self._lines[self._cursor_line] = line[:self._cursor_col]
        elif self._cursor_line < len(self._lines) - 1:
            self._push_undo()
            self._kill_ring.push("\n", prepend=False, accumulate=self._last_action == "kill")
            self._last_action = "kill"
            next_line = self._lines[self._cursor_line + 1]
            self._lines[self._cursor_line] = line + next_line
            del self._lines[self._cursor_line + 1]
        if self.on_change:
            self.on_change(self.get_text())

    def _delete_word_backward(self) -> None:
        self._history_index = -1
        line = self._lines[self._cursor_line]
        if self._cursor_col == 0:
            if self._cursor_line > 0:
                self._push_undo()
                self._kill_ring.push("\n", prepend=True, accumulate=self._last_action == "kill")
                self._last_action = "kill"
                prev = self._lines[self._cursor_line - 1]
                self._lines[self._cursor_line - 1] = prev + line
                del self._lines[self._cursor_line]
                self._cursor_line -= 1
                self._set_cursor_col(len(prev))
        else:
            self._push_undo()
            was_kill = self._last_action == "kill"
            old_col = self._cursor_col
            self._move_word_backward()
            del_from = self._cursor_col
            self._cursor_col = old_col
            deleted = line[del_from:self._cursor_col]
            self._kill_ring.push(deleted, prepend=True, accumulate=was_kill)
            self._last_action = "kill"
            self._lines[self._cursor_line] = line[:del_from] + line[self._cursor_col:]
            self._set_cursor_col(del_from)
        if self.on_change:
            self.on_change(self.get_text())

    def _delete_word_forward(self) -> None:
        self._history_index = -1
        line = self._lines[self._cursor_line]
        if self._cursor_col >= len(line):
            if self._cursor_line < len(self._lines) - 1:
                self._push_undo()
                self._kill_ring.push("\n", prepend=False, accumulate=self._last_action == "kill")
                self._last_action = "kill"
                next_line = self._lines[self._cursor_line + 1]
                self._lines[self._cursor_line] = line + next_line
                del self._lines[self._cursor_line + 1]
        else:
            self._push_undo()
            was_kill = self._last_action == "kill"
            old_col = self._cursor_col
            self._move_word_forward()
            del_to = self._cursor_col
            self._cursor_col = old_col
            deleted = line[self._cursor_col:del_to]
            self._kill_ring.push(deleted, prepend=False, accumulate=was_kill)
            self._last_action = "kill"
            self._lines[self._cursor_line] = line[:self._cursor_col] + line[del_to:]
        if self.on_change:
            self.on_change(self.get_text())

    def _yank(self) -> None:
        if not len(self._kill_ring):
            return
        self._push_undo()
        text = self._kill_ring.peek()
        if text:
            self._insert_text_internal(text)
        self._last_action = "yank"

    def _yank_pop(self) -> None:
        if self._last_action != "yank" or len(self._kill_ring) <= 1:
            return
        self._push_undo()
        prev = self._kill_ring.peek() or ""
        # Delete previously yanked text
        new_col = self._cursor_col - len(prev)
        line = self._lines[self._cursor_line]
        self._lines[self._cursor_line] = line[:new_col] + line[self._cursor_col:]
        self._set_cursor_col(new_col)
        self._kill_ring.rotate()
        text = self._kill_ring.peek() or ""
        self._insert_text_internal(text)
        self._last_action = "yank"


    def _move_cursor(self, delta_line: int, delta_col: int) -> None:
        self._last_action = None
        if delta_line != 0:
            vl_map = self._build_visual_line_map(self._last_width)
            cur_vl = self._find_current_visual_line(vl_map)
            target = cur_vl + delta_line
            if 0 <= target < len(vl_map):
                self._move_to_visual_line(vl_map, cur_vl, target)

        if delta_col != 0:
            line = self._lines[self._cursor_line]
            if delta_col > 0:
                if self._cursor_col < len(line):
                    gs = _graphemes(line[self._cursor_col:])
                    first = gs[0] if gs else ""
                    self._set_cursor_col(self._cursor_col + len(first))
                elif self._cursor_line < len(self._lines) - 1:
                    self._cursor_line += 1
                    self._set_cursor_col(0)
            else:
                if self._cursor_col > 0:
                    gs = _graphemes(line[:self._cursor_col])
                    last = gs[-1] if gs else ""
                    self._set_cursor_col(self._cursor_col - len(last))
                elif self._cursor_line > 0:
                    self._cursor_line -= 1
                    self._set_cursor_col(len(self._lines[self._cursor_line]))

    def _move_word_backward(self) -> None:
        self._last_action = None
        line = self._lines[self._cursor_line]
        if self._cursor_col == 0:
            if self._cursor_line > 0:
                self._cursor_line -= 1
                self._set_cursor_col(len(self._lines[self._cursor_line]))
            return
        before = line[:self._cursor_col]
        gs = _graphemes(before)
        new_col = self._cursor_col
        while gs and is_whitespace_char(gs[-1]):
            new_col -= len(gs.pop())
        if gs:
            if is_punctuation_char(gs[-1]):
                while gs and is_punctuation_char(gs[-1]):
                    new_col -= len(gs.pop())
            else:
                while gs and not is_whitespace_char(gs[-1]) and not is_punctuation_char(gs[-1]):
                    new_col -= len(gs.pop())
        self._set_cursor_col(new_col)

    def _move_word_forward(self) -> None:
        self._last_action = None
        line = self._lines[self._cursor_line]
        if self._cursor_col >= len(line):
            if self._cursor_line < len(self._lines) - 1:
                self._cursor_line += 1
                self._set_cursor_col(0)
            return
        after = line[self._cursor_col:]
        gs = _graphemes(after)
        new_col = self._cursor_col
        idx = 0
        while idx < len(gs) and is_whitespace_char(gs[idx]):
            new_col += len(gs[idx])
            idx += 1
        if idx < len(gs):
            if is_punctuation_char(gs[idx]):
                while idx < len(gs) and is_punctuation_char(gs[idx]):
                    new_col += len(gs[idx])
                    idx += 1
            else:
                while idx < len(gs) and not is_whitespace_char(gs[idx]) and not is_punctuation_char(gs[idx]):
                    new_col += len(gs[idx])
                    idx += 1
        self._set_cursor_col(new_col)

    def _page_scroll(self, direction: int) -> None:
        self._last_action = None
        page_size = max(5, self._tui.terminal.rows * 3 // 10)
        vl_map = self._build_visual_line_map(self._last_width)
        cur_vl = self._find_current_visual_line(vl_map)
        target = max(0, min(len(vl_map) - 1, cur_vl + direction * page_size))
        self._move_to_visual_line(vl_map, cur_vl, target)

    def _jump_to_char(self, char: str, direction: str) -> None:
        self._last_action = None
        forward = direction == "forward"
        lines = self._lines
        end = len(lines) if forward else -1
        step = 1 if forward else -1
        li = self._cursor_line
        while li != end:
            line = lines[li]
            is_cur = li == self._cursor_line
            if is_cur:
                search_from = self._cursor_col + 1 if forward else self._cursor_col - 1
            else:
                search_from = 0 if forward else len(line) - 1
            idx = line.find(char, search_from) if forward else line.rfind(char, 0, search_from + 1 if search_from >= 0 else 0)
            if idx != -1:
                self._cursor_line = li
                self._set_cursor_col(idx)
                return
            li += step


    def _build_visual_line_map(self, width: int) -> list[dict]:
        vl: list[dict] = []
        for i, line in enumerate(self._lines):
            if not line:
                vl.append({"logical_line": i, "start_col": 0, "length": 0})
            elif visible_width(line) <= width:
                vl.append({"logical_line": i, "start_col": 0, "length": len(line)})
            else:
                chunks = word_wrap_line(line, width)
                for chunk in chunks:
                    vl.append({
                        "logical_line": i,
                        "start_col": chunk["start_index"],
                        "length": chunk["end_index"] - chunk["start_index"],
                    })
        return vl

    def _find_current_visual_line(self, vl_map: list[dict]) -> int:
        for i, vl in enumerate(vl_map):
            if vl["logical_line"] == self._cursor_line:
                col_in_seg = self._cursor_col - vl["start_col"]
                is_last = (
                    i == len(vl_map) - 1
                    or vl_map[i + 1]["logical_line"] != vl["logical_line"]
                )
                if col_in_seg >= 0 and (col_in_seg < vl["length"] or (is_last and col_in_seg <= vl["length"])):
                    return i
        return len(vl_map) - 1

    def _move_to_visual_line(self, vl_map: list[dict], cur: int, target: int) -> None:
        cur_vl = vl_map[cur]
        tgt_vl = vl_map[target]
        cur_vis_col = self._cursor_col - cur_vl["start_col"]

        is_last_src = cur == len(vl_map) - 1 or vl_map[cur + 1]["logical_line"] != cur_vl["logical_line"]
        src_max = cur_vl["length"] if is_last_src else max(0, cur_vl["length"] - 1)
        is_last_tgt = target == len(vl_map) - 1 or vl_map[target + 1]["logical_line"] != tgt_vl["logical_line"]
        tgt_max = tgt_vl["length"] if is_last_tgt else max(0, tgt_vl["length"] - 1)

        move_col = self._compute_vertical_col(cur_vis_col, src_max, tgt_max)
        self._cursor_line = tgt_vl["logical_line"]
        target_col = tgt_vl["start_col"] + move_col
        line = self._lines[tgt_vl["logical_line"]]
        self._cursor_col = min(target_col, len(line))

    def _compute_vertical_col(self, cur_col: int, src_max: int, tgt_max: int) -> int:
        has_pref = self._preferred_visual_col is not None
        in_middle = cur_col < src_max
        target_short = tgt_max < cur_col

        if not has_pref or in_middle:
            if target_short:
                self._preferred_visual_col = cur_col
                return tgt_max
            self._preferred_visual_col = None
            return cur_col

        cant_fit = tgt_max < self._preferred_visual_col  # type: ignore[operator]
        if target_short or cant_fit:
            return tgt_max

        result = self._preferred_visual_col  # type: ignore[assignment]
        self._preferred_visual_col = None
        return result  # type: ignore[return-value]

    def _is_empty(self) -> bool:
        return len(self._lines) == 1 and self._lines[0] == ""

    def _should_submit_on_backslash_enter(self, data: str, kb: Any) -> bool:
        """Check if backslash+enter should submit (when submit is mapped to shift+enter)."""
        if self.disable_submit:
            return False
        if not matches_key(data, "enter"):
            return False
        submit_keys = kb.get_keys("tui.input.submit")
        has_shift_enter = "shift+enter" in submit_keys or "shift+return" in submit_keys
        if not has_shift_enter:
            return False
        current = self._lines[self._cursor_line] or ""
        return self._cursor_col > 0 and current[self._cursor_col - 1 : self._cursor_col] == "\\"

    def _should_chain_slash_autocomplete_on_tab(self) -> bool:
        """Check if tab selection should chain into slash argument completions."""
        if self._autocomplete_state != "regular":
            return False
        current = self._lines[self._cursor_line] or ""
        before = current[: self._cursor_col]
        return self._is_in_slash_context(before) and " " not in before.strip()

    def _is_bare_completed_slash_at_cursor(self) -> bool:
        """Check if cursor is right after a completed bare slash command (e.g. '/model ')."""
        current = self._lines[self._cursor_line] or ""
        if self._cursor_col != len(current):
            return False
        before = current[: self._cursor_col].lstrip()
        return bool(re.match(r"^/\S+ $", before))

    def _on_first_visual_line(self) -> bool:
        vl = self._build_visual_line_map(self._last_width)
        return self._find_current_visual_line(vl) == 0

    def _on_last_visual_line(self) -> bool:
        vl = self._build_visual_line_map(self._last_width)
        return self._find_current_visual_line(vl) == len(vl) - 1

    def _navigate_history(self, direction: int) -> None:
        self._last_action = None
        if not self._history:
            return
        new_idx = self._history_index - direction
        if new_idx < -1 or new_idx >= len(self._history):
            return
        if self._history_index == -1 and new_idx >= 0:
            self._push_undo()
        self._history_index = new_idx
        if self._history_index == -1:
            self._set_text_internal("")
        else:
            self._set_text_internal(self._history[self._history_index])

    def _is_at_start(self) -> bool:
        if self._cursor_line != 0:
            return False
        before = self._lines[self._cursor_line][:self._cursor_col]
        return before.strip() in ("", "/")

    def _is_in_slash_context(self, text: str) -> bool:
        return self._cursor_line == 0 and text.lstrip().startswith("/")


    def _try_trigger_autocomplete(self) -> None:
        if not self._autocomplete_provider:
            return
        sugs = self._autocomplete_provider.get_suggestions(
            self._lines, self._cursor_line, self._cursor_col
        )
        if sugs and sugs["items"]:
            self._autocomplete_prefix = sugs["prefix"]
            from pana.tui.components.select_list import SelectItem, SelectList
            from pana.tui.components.select_list import SelectListTheme as SLT

            items = [
                SelectItem(value=it.value, label=it.label, description=it.description)
                for it in sugs["items"]
            ]
            theme = SLT(
                selected_prefix=self._theme.select_list.selected_prefix,
                selected_text=self._theme.select_list.selected_text,
                description=self._theme.select_list.description,
                scroll_info=self._theme.select_list.scroll_info,
                no_match=self._theme.select_list.no_match,
            )
            self._autocomplete_list = SelectList(items, self._autocomplete_max_visible, theme)
            best = self._get_best_autocomplete_match_index(sugs["items"], sugs["prefix"])
            if best > 0:
                self._autocomplete_list.set_selected_index(best)
            self._autocomplete_state = "regular"
        else:
            self._cancel_autocomplete()

    def _update_autocomplete(self) -> None:
        if not self._autocomplete_state or not self._autocomplete_provider:
            return
        if self._autocomplete_state == "force":
            self._force_file_autocomplete(is_update=True)
            return
        sugs = self._autocomplete_provider.get_suggestions(
            self._lines, self._cursor_line, self._cursor_col
        )
        if sugs and sugs["items"]:
            self._autocomplete_prefix = sugs["prefix"]
            from pana.tui.components.select_list import SelectItem, SelectList
            from pana.tui.components.select_list import SelectListTheme as SLT

            items = [
                SelectItem(value=it.value, label=it.label, description=it.description)
                for it in sugs["items"]
            ]
            theme = SLT(
                selected_prefix=self._theme.select_list.selected_prefix,
                selected_text=self._theme.select_list.selected_text,
                description=self._theme.select_list.description,
                scroll_info=self._theme.select_list.scroll_info,
                no_match=self._theme.select_list.no_match,
            )
            self._autocomplete_list = SelectList(items, self._autocomplete_max_visible, theme)
            best = self._get_best_autocomplete_match_index(sugs["items"], sugs["prefix"])
            if best > 0:
                self._autocomplete_list.set_selected_index(best)
        else:
            self._cancel_autocomplete()

    def _cancel_autocomplete(self) -> None:
        self._autocomplete_state = None
        self._autocomplete_list = None
        self._autocomplete_prefix = ""

    def is_showing_autocomplete(self) -> bool:
        return self._autocomplete_state is not None

    def _handle_tab(self) -> None:
        if not self._autocomplete_provider:
            return
        before = self._lines[self._cursor_line][:self._cursor_col]
        if self._is_in_slash_context(before) and " " not in before.lstrip():
            self._try_trigger_autocomplete()
        else:
            self._force_file_autocomplete()

    def _force_file_autocomplete(self, *, is_update: bool = False) -> None:
        provider = self._autocomplete_provider
        if not provider:
            return
        get_force = getattr(provider, "get_force_file_suggestions", None)
        if not get_force:
            return
        sugs = get_force(self._lines, self._cursor_line, self._cursor_col)
        if not sugs or not sugs["items"]:
            if is_update:
                self._cancel_autocomplete()
            return
        # Single result on initial trigger: auto-apply without showing the menu
        if len(sugs["items"]) == 1 and not is_update:
            from pana.tui.autocomplete import AutocompleteItem
            item = sugs["items"][0]
            if isinstance(item, dict):
                item = AutocompleteItem(value=item["value"], label=item["label"], description=item.get("description"))
            self._push_undo()
            self._last_action = None
            r = provider.apply_completion(
                self._lines, self._cursor_line, self._cursor_col,
                item, sugs["prefix"],
            )
            self._lines = r["lines"]
            self._cursor_line = r["cursor_line"]
            self._set_cursor_col(r["cursor_col"])
            if self.on_change:
                self.on_change(self.get_text())
            return
        # Multiple results: show menu in force mode
        self._autocomplete_prefix = sugs["prefix"]
        from pana.tui.components.select_list import SelectItem, SelectList
        from pana.tui.components.select_list import SelectListTheme as SLT
        items = [
            SelectItem(value=it.value, label=it.label, description=it.description)
            for it in sugs["items"]
        ]
        theme = SLT(
            selected_prefix=self._theme.select_list.selected_prefix,
            selected_text=self._theme.select_list.selected_text,
            description=self._theme.select_list.description,
            scroll_info=self._theme.select_list.scroll_info,
            no_match=self._theme.select_list.no_match,
        )
        self._autocomplete_list = SelectList(items, self._autocomplete_max_visible, theme)
        best = self._get_best_autocomplete_match_index(sugs["items"], sugs["prefix"])
        if best > 0:
            self._autocomplete_list.set_selected_index(best)
        self._autocomplete_state = "force"

    def _get_best_autocomplete_match_index(self, items: list, prefix: str) -> int:
        for i, item in enumerate(items):
            val = item.value if hasattr(item, "value") else item["value"]
            if val == prefix:
                return i
        for i, item in enumerate(items):
            val = item.value if hasattr(item, "value") else item["value"]
            if val.startswith(prefix):
                return i
        return 0
