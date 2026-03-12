"""Single-line text input component with horizontal scrolling, kill ring, and undo."""
from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

import grapheme

from app.tui.keybindings import get_editor_keybindings
from app.tui.keys import decode_kitty_printable
from app.tui.kill_ring import KillRing
from app.tui.tui import CURSOR_MARKER
from app.tui.undo_stack import UndoStack
from app.tui.utils import (
    is_punctuation_char,
    is_whitespace_char,
    slice_by_column,
    visible_width,
)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

PROMPT = "> "
PROMPT_WIDTH = visible_width(PROMPT)

_PASTE_START = "\x1b[200~"
_PASTE_END = "\x1b[201~"


class _UndoState(TypedDict):
    value: str
    cursor: int


# ---------------------------------------------------------------------------
# Input component
# ---------------------------------------------------------------------------


class Input:
    """Full-featured single-line text input.

    Features:
    - Horizontal scrolling when text exceeds available width
    - Fake cursor rendering (inverse video)
    - Bracketed paste handling
    - Emacs-style kill ring (kill / yank / yank-pop)
    - Undo support with coalescing of consecutive character typing
    - Word movement (boundaries at whitespace / punctuation)
    - CURSOR_MARKER emission when focused (for IME)
    """

    def __init__(
        self,
        *,
        on_submit: Callable[[str], None] | None = None,
        on_escape: Callable[[], None] | None = None,
        initial_value: str = "",
    ) -> None:
        self.value: str = initial_value
        self.cursor: int = len(initial_value)
        self.focused: bool = False

        self.on_submit = on_submit
        self.on_escape = on_escape

        self._kill_ring = KillRing()
        self._undo_stack: UndoStack[_UndoState] = UndoStack()

        # Bracketed paste buffering
        self._paste_buffer: str | None = None

        # Kill-ring accumulation tracking
        self._last_action: str | None = None

        # Undo coalescing: track whether we're in a run of character inserts
        self._typing_run: bool = False

    # ------------------------------------------------------------------
    # Grapheme helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _graphemes(text: str) -> list[str]:
        return list(grapheme.graphemes(text))

    # ------------------------------------------------------------------
    # Undo helpers
    # ------------------------------------------------------------------

    def _snapshot(self) -> _UndoState:
        return {"value": self.value, "cursor": self.cursor}

    def _push_undo(self) -> None:
        self._undo_stack.push(self._snapshot())

    def _pop_undo(self) -> None:
        state = self._undo_stack.pop()
        if state is not None:
            self.value = state["value"]
            self.cursor = state["cursor"]

    def _break_typing_run(self) -> None:
        self._typing_run = False

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def _insert_text(self, text: str) -> None:
        self.value = self.value[: self.cursor] + text + self.value[self.cursor :]
        self.cursor += len(text)

    def _delete_range(self, start: int, end: int) -> str:
        deleted = self.value[start:end]
        self.value = self.value[:start] + self.value[end:]
        if self.cursor > end:
            self.cursor -= end - start
        elif self.cursor > start:
            self.cursor = start
        return deleted

    # ------------------------------------------------------------------
    # Word boundary helpers
    # ------------------------------------------------------------------

    def _word_left(self, pos: int) -> int:
        """Return position of the start of the word to the left of *pos*."""
        if pos <= 0:
            return 0
        gs = self._graphemes(self.value[:pos])
        i = len(gs) - 1
        # Skip whitespace
        while i >= 0 and is_whitespace_char(gs[i][0]):
            i -= 1
        if i < 0:
            return 0
        # Determine category of first non-whitespace grapheme
        is_punct = is_punctuation_char(gs[i][0])
        # Skip same-category run
        while i >= 0:
            ch = gs[i][0]
            if is_whitespace_char(ch):
                break
            if is_punctuation_char(ch) != is_punct:
                break
            i -= 1
        return len("".join(gs[: i + 1]))

    def _word_right(self, pos: int) -> int:
        """Return position of the end of the word to the right of *pos*."""
        if pos >= len(self.value):
            return len(self.value)
        gs = self._graphemes(self.value[pos:])
        i = 0
        # Skip whitespace
        while i < len(gs) and is_whitespace_char(gs[i][0]):
            i += 1
        if i >= len(gs):
            return len(self.value)
        is_punct = is_punctuation_char(gs[i][0])
        while i < len(gs):
            ch = gs[i][0]
            if is_whitespace_char(ch):
                break
            if is_punctuation_char(ch) != is_punct:
                break
            i += 1
        return pos + len("".join(gs[:i]))

    # ------------------------------------------------------------------
    # Cursor movement
    # ------------------------------------------------------------------

    def _move_left(self) -> None:
        if self.cursor <= 0:
            return
        gs = self._graphemes(self.value[: self.cursor])
        if gs:
            self.cursor -= len(gs[-1])

    def _move_right(self) -> None:
        if self.cursor >= len(self.value):
            return
        gs = self._graphemes(self.value[self.cursor :])
        if gs:
            self.cursor += len(gs[0])

    def _move_word_left(self) -> None:
        self.cursor = self._word_left(self.cursor)

    def _move_word_right(self) -> None:
        self.cursor = self._word_right(self.cursor)

    def _move_line_start(self) -> None:
        self.cursor = 0

    def _move_line_end(self) -> None:
        self.cursor = len(self.value)

    # ------------------------------------------------------------------
    # Deletion actions
    # ------------------------------------------------------------------

    def _delete_char_backward(self) -> None:
        if self.cursor <= 0:
            return
        self._push_undo()
        gs = self._graphemes(self.value[: self.cursor])
        if gs:
            remove = gs[-1]
            start = self.cursor - len(remove)
            self._delete_range(start, self.cursor)

    def _delete_char_forward(self) -> None:
        if self.cursor >= len(self.value):
            return
        self._push_undo()
        gs = self._graphemes(self.value[self.cursor :])
        if gs:
            end = self.cursor + len(gs[0])
            self._delete_range(self.cursor, end)

    def _delete_word_backward(self) -> None:
        if self.cursor <= 0:
            return
        self._push_undo()
        new_pos = self._word_left(self.cursor)
        deleted = self._delete_range(new_pos, self.cursor)
        accumulate = self._last_action in ("deleteWordBackward", "deleteWordForward")
        self._kill_ring.push(deleted, prepend=True, accumulate=accumulate)

    def _delete_word_forward(self) -> None:
        if self.cursor >= len(self.value):
            return
        self._push_undo()
        new_pos = self._word_right(self.cursor)
        deleted = self._delete_range(self.cursor, new_pos)
        accumulate = self._last_action in ("deleteWordBackward", "deleteWordForward")
        self._kill_ring.push(deleted, prepend=False, accumulate=accumulate)

    def _delete_to_line_start(self) -> None:
        if self.cursor <= 0:
            return
        self._push_undo()
        deleted = self._delete_range(0, self.cursor)
        accumulate = self._last_action in ("deleteToLineStart", "deleteToLineEnd")
        self._kill_ring.push(deleted, prepend=True, accumulate=accumulate)

    def _delete_to_line_end(self) -> None:
        if self.cursor >= len(self.value):
            return
        self._push_undo()
        deleted = self._delete_range(self.cursor, len(self.value))
        accumulate = self._last_action in ("deleteToLineStart", "deleteToLineEnd")
        self._kill_ring.push(deleted, prepend=False, accumulate=accumulate)

    # ------------------------------------------------------------------
    # Kill ring
    # ------------------------------------------------------------------

    def _yank(self) -> None:
        text = self._kill_ring.peek()
        if text is None:
            return
        self._push_undo()
        self._insert_text(text)

    def _yank_pop(self) -> None:
        prev = self._kill_ring.peek()
        if prev is None:
            return
        self._kill_ring.rotate()
        curr = self._kill_ring.peek()
        if curr is None or curr == prev:
            return
        self._push_undo()
        # Remove the previously yanked text and insert the rotated one
        start = self.cursor - len(prev)
        if start >= 0 and self.value[start : self.cursor] == prev:
            self._delete_range(start, self.cursor)
            self._insert_text(curr)

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def handle_input(self, data: str) -> None:
        """Process a chunk of terminal input data."""
        # --- Bracketed paste handling ---
        if self._paste_buffer is not None:
            end_idx = data.find(_PASTE_END)
            if end_idx == -1:
                self._paste_buffer += data
                return
            self._paste_buffer += data[:end_idx]
            pasted = self._paste_buffer.replace("\n", " ").replace("\r", " ")
            self._paste_buffer = None
            if pasted:
                self._push_undo()
                self._break_typing_run()
                self._insert_text(pasted)
                self._last_action = "paste"
            remainder = data[end_idx + len(_PASTE_END) :]
            if remainder:
                self.handle_input(remainder)
            return

        if data.startswith(_PASTE_START):
            self._paste_buffer = ""
            self.handle_input(data[len(_PASTE_START) :])
            return

        kb = get_editor_keybindings()

        # --- Keybinding matching ---
        if kb.matches(data, "selectCancel"):
            self._break_typing_run()
            self._last_action = "selectCancel"
            if self.on_escape:
                self.on_escape()
            return

        if kb.matches(data, "undo"):
            self._break_typing_run()
            self._last_action = "undo"
            self._pop_undo()
            return

        if kb.matches(data, "submit"):
            self._break_typing_run()
            self._last_action = "submit"
            if self.on_submit:
                self.on_submit(self.value)
            return

        if kb.matches(data, "deleteCharBackward"):
            self._break_typing_run()
            self._last_action = "deleteCharBackward"
            self._delete_char_backward()
            return

        if kb.matches(data, "deleteCharForward"):
            self._break_typing_run()
            self._last_action = "deleteCharForward"
            self._delete_char_forward()
            return

        if kb.matches(data, "deleteWordBackward"):
            self._break_typing_run()
            self._last_action = "deleteWordBackward"
            self._delete_word_backward()
            return

        if kb.matches(data, "deleteWordForward"):
            self._break_typing_run()
            self._last_action = "deleteWordForward"
            self._delete_word_forward()
            return

        if kb.matches(data, "deleteToLineStart"):
            self._break_typing_run()
            self._last_action = "deleteToLineStart"
            self._delete_to_line_start()
            return

        if kb.matches(data, "deleteToLineEnd"):
            self._break_typing_run()
            self._last_action = "deleteToLineEnd"
            self._delete_to_line_end()
            return

        if kb.matches(data, "yank"):
            self._break_typing_run()
            self._last_action = "yank"
            self._yank()
            return

        if kb.matches(data, "yankPop"):
            if self._last_action in ("yank", "yankPop"):
                self._last_action = "yankPop"
                self._yank_pop()
            return

        if kb.matches(data, "cursorLeft"):
            self._break_typing_run()
            self._last_action = "cursorLeft"
            self._move_left()
            return

        if kb.matches(data, "cursorRight"):
            self._break_typing_run()
            self._last_action = "cursorRight"
            self._move_right()
            return

        if kb.matches(data, "cursorLineStart"):
            self._break_typing_run()
            self._last_action = "cursorLineStart"
            self._move_line_start()
            return

        if kb.matches(data, "cursorLineEnd"):
            self._break_typing_run()
            self._last_action = "cursorLineEnd"
            self._move_line_end()
            return

        if kb.matches(data, "cursorWordLeft"):
            self._break_typing_run()
            self._last_action = "cursorWordLeft"
            self._move_word_left()
            return

        if kb.matches(data, "cursorWordRight"):
            self._break_typing_run()
            self._last_action = "cursorWordRight"
            self._move_word_right()
            return

        # --- Kitty printable decode ---
        ch = decode_kitty_printable(data)
        if ch is not None:
            self._handle_char_insert(ch)
            return

        # --- Regular character input ---
        if len(data) == 1 and ord(data) >= 0x20 and data != "\x7f":
            self._handle_char_insert(data)
            return

        # Multi-byte UTF-8 character (not a control/escape sequence)
        if len(data) >= 1 and ord(data[0]) >= 0x80 and not data.startswith("\x1b"):
            self._handle_char_insert(data)
            return

    def _handle_char_insert(self, ch: str) -> None:
        """Insert a printable character, coalescing undo for consecutive typing."""
        if not self._typing_run:
            self._push_undo()
            self._typing_run = True
        elif is_whitespace_char(ch[0]):
            # Break undo coalescing on whitespace
            self._push_undo()

        self._insert_text(ch)
        self._last_action = "type"

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, width: int) -> list[str]:
        """Render the input as a single line of *width* columns.

        Returns a one-element list (single-line component).
        """
        content_width = max(0, width - PROMPT_WIDTH)
        if content_width <= 0:
            return [PROMPT[:width]]

        text = self.value
        text_width = visible_width(text)
        cursor_offset = visible_width(text[: self.cursor])

        # Determine scroll offset so cursor stays visible
        scroll = self._compute_scroll(text_width, cursor_offset, content_width)

        # Build the line with fake cursor
        cursor_col_in_viewport = cursor_offset - scroll

        # Extract the grapheme at cursor position for the fake cursor char
        cursor_char, _ = self._extract_cursor_char(text, self.cursor)

        # Build before-cursor text (from scroll to cursor)
        before_text = slice_by_column(text, scroll, cursor_col_in_viewport)
        before_w = visible_width(before_text)

        # Build after-cursor text (from cursor+1 grapheme to end of viewport)
        cursor_char_width = visible_width(cursor_char) if cursor_char else 1
        after_col = cursor_col_in_viewport + cursor_char_width
        after_remaining_width = max(0, content_width - after_col)
        after_text = slice_by_column(
            text, scroll + after_col, after_remaining_width
        )
        after_w = visible_width(after_text)

        # Render the cursor character
        display_cursor_char = cursor_char if cursor_char else " "
        cursor_rendered = f"\x1b[7m{display_cursor_char}\x1b[27m"

        # Assemble
        cursor_marker = CURSOR_MARKER if self.focused else ""
        line_content = before_text + cursor_marker + cursor_rendered + after_text

        # Pad to fill content width
        used = before_w + visible_width(display_cursor_char) + after_w
        padding = max(0, content_width - used)

        return [PROMPT + line_content + " " * padding]

    @staticmethod
    def _compute_scroll(
        text_width: int, cursor_offset: int, viewport_width: int
    ) -> int:
        """Compute horizontal scroll so that the cursor is visible and roughly centred."""
        if text_width <= viewport_width:
            return 0

        # Centre the cursor in the viewport
        ideal = cursor_offset - viewport_width // 2
        max_scroll = max(0, text_width - viewport_width)
        return max(0, min(ideal, max_scroll))

    @staticmethod
    def _extract_cursor_char(text: str, cursor: int) -> tuple[str, str]:
        """Return ``(char_at_cursor, rest_after_cursor)``.

        *char_at_cursor* is the grapheme cluster at the cursor position,
        or ``""`` if the cursor is at the end of the text.
        """
        if cursor >= len(text):
            return ("", "")
        tail = text[cursor:]
        gs = list(grapheme.graphemes(tail))
        if not gs:
            return ("", "")
        char = gs[0]
        rest = "".join(gs[1:])
        return (char, rest)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_value(self) -> str:
        return self.value

    def set_value(self, value: str, *, cursor: int | None = None) -> None:
        """Programmatically set the value and optionally the cursor position."""
        self._push_undo()
        self._break_typing_run()
        self.value = value
        self.cursor = cursor if cursor is not None else len(value)

    def clear(self) -> None:
        """Clear the input."""
        self.set_value("")
