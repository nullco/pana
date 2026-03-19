"""TUI core engine with differential rendering and overlay system.

Provides a Component protocol, Container, overlay management, and the main
TUI class that drives the render loop against a Terminal backend.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import re

from app.tui.keys import is_key_release, matches_key
from app.tui.terminal import Terminal
from app.tui.terminal_image import is_image_line
from app.tui.utils import extract_segments, visible_width

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CURSOR_MARKER = "\x1b_pi:c\x07"  # APC zero-width cursor position marker
_SEGMENT_RESET = "\x1b[0m\x1b]8;;\x07"

# ---------------------------------------------------------------------------
# Stdin splitting
# ---------------------------------------------------------------------------

# Matches a single escape sequence (CSI, OSC, SS3, APC, or bare ESC + char)
_ESC_SEQ_RE = re.compile(
    r"\x1b"
    r"(?:"
    r"\[[0-9;:?]*[A-Za-z~]"   # CSI  … final byte
    r"|\][^\x07]*\x07"         # OSC  … ST (BEL)
    r"|O[A-Za-z]"              # SS3  letter
    r"|_[^\x07]*\x07"          # APC  … ST (BEL)
    r"|."                      # bare ESC + one char  (e.g. alt+key)
    r")"
)


def _split_stdin(data: str) -> list[str]:
    """Split a raw stdin buffer into individual key events.

    A single ``os.read`` may return multiple key sequences concatenated
    together (e.g. rapid typing or an escape sequence followed by a
    printable character).  This function peels them apart so each one can
    be dispatched individually.
    """
    if len(data) <= 1:
        return [data] if data else []

    chunks: list[str] = []
    i = 0
    n = len(data)

    while i < n:
        # Bracketed paste — keep as one blob until the end marker
        if data[i:i + 6] == "\x1b[200~":
            end = data.find("\x1b[201~", i + 6)
            if end != -1:
                chunks.append(data[i:end + 6])
                i = end + 6
            else:
                chunks.append(data[i:])
                break
            continue

        if data[i] == "\x1b":
            m = _ESC_SEQ_RE.match(data, i)
            if m:
                chunks.append(m.group(0))
                i = m.end()
                continue
            # Lone ESC at end of buffer
            chunks.append(data[i])
            i += 1
            continue

        # Plain character (including multi-byte UTF-8 already decoded)
        chunks.append(data[i])
        i += 1

    return chunks

# ---------------------------------------------------------------------------
# Component / Focusable protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class Component(Protocol):
    def render(self, width: int) -> list[str]: ...


@runtime_checkable
class Focusable(Protocol):
    focused: bool


def is_focusable(component: object) -> bool:
    """Type-guard: does *component* expose a ``focused`` attribute?"""
    return isinstance(component, Focusable)


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------


class Container:
    """Component that contains other components."""

    def __init__(self) -> None:
        self.children: list[Component] = []

    def add_child(self, component: Component) -> None:
        self.children.append(component)

    def remove_child(self, component: Component) -> None:
        try:
            self.children.remove(component)
        except ValueError:
            pass

    def clear(self) -> None:
        self.children.clear()

    def invalidate(self) -> None:
        for child in self.children:
            if hasattr(child, "invalidate"):
                child.invalidate()

    def render(self, width: int) -> list[str]:
        lines: list[str] = []
        for child in self.children:
            lines.extend(child.render(width))
        return lines


# ---------------------------------------------------------------------------
# Overlay types
# ---------------------------------------------------------------------------

OverlayAnchor = str  # "center", "top-left", "top-right", "bottom-left", ...

SizeValue = int | str  # int or e.g. "50%"


@dataclass
class OverlayMargin:
    top: int = 0
    right: int = 0
    bottom: int = 0
    left: int = 0


@dataclass
class OverlayOptions:
    width: SizeValue | None = None
    min_width: int | None = None
    max_height: SizeValue | None = None
    anchor: str = "center"
    offset_x: int = 0
    offset_y: int = 0
    row: SizeValue | None = None
    col: SizeValue | None = None
    margin: OverlayMargin | int | None = None
    visible: Callable[[], bool] | None = None
    non_capturing: bool = False


# ---------------------------------------------------------------------------
# OverlayHandle
# ---------------------------------------------------------------------------


class OverlayHandle:
    """Handle returned by :meth:`TUI.show_overlay`."""

    def __init__(
        self,
        component: Component,
        options: OverlayOptions,
        tui: TUI,
        focus_order: int,
    ) -> None:
        self.component = component
        self.options = options
        self._tui = tui
        self._hidden = False
        self._focused = True
        self.focus_order = focus_order

    # -- visibility ----------------------------------------------------------

    def hide(self) -> None:
        self.set_hidden(True)

    def set_hidden(self, hidden: bool) -> None:
        if self._hidden == hidden:
            return
        self._hidden = hidden
        self._tui.request_render()

    def is_hidden(self) -> bool:
        return self._hidden

    # -- focus ---------------------------------------------------------------

    def focus(self) -> None:
        self._focused = True

    def unfocus(self) -> None:
        self._focused = False

    def is_focused(self) -> bool:
        return self._focused


# ---------------------------------------------------------------------------
# Overlay entry (internal)
# ---------------------------------------------------------------------------


@dataclass
class _OverlayEntry:
    handle: OverlayHandle
    component: Component
    options: OverlayOptions
    previous_focus: Component | None = None


# ---------------------------------------------------------------------------
# TUI
# ---------------------------------------------------------------------------


class TUI(Container):
    """Main TUI engine with differential rendering and overlay support."""

    def __init__(self, terminal: Terminal) -> None:
        super().__init__()
        self.terminal = terminal

        # Render state
        self.previous_lines: list[str] | None = None
        self.previous_width: int = 0
        self.previous_height: int = 0
        self.focused_component: Component | None = None
        self.render_requested: bool = False
        self.cursor_row: int | None = None
        self.hardware_cursor_row: int | None = None
        self.max_lines_rendered: int = 0
        self.previous_viewport_top: int = 0

        # Overlay system
        self.overlay_stack: list[_OverlayEntry] = []
        self.focus_order_counter: int = 0

        # Input listeners
        self._input_listeners: list[Callable[[str], None]] = []

        # Debug callback
        self.on_debug: Callable[[str], None] | None = None

        # Config flags
        self.show_hardware_cursor: bool = True
        self.clear_on_shrink: bool = False

        self.stopped: bool = False

    # ------------------------------------------------------------------
    # Focus management
    # ------------------------------------------------------------------

    def add_input_listener(self, listener: Callable[[str], None]) -> None:
        self._input_listeners.append(listener)

    def remove_input_listener(self, listener: Callable[[str], None]) -> None:
        try:
            self._input_listeners.remove(listener)
        except ValueError:
            pass

    def set_focus(self, component: Component | None) -> None:
        """Set focus to *component*, clearing the previous focus."""
        if self.focused_component is not None and is_focusable(self.focused_component):
            self.focused_component.focused = False
        self.focused_component = component
        if component is not None and is_focusable(component):
            component.focused = True

    # ------------------------------------------------------------------
    # Overlay system
    # ------------------------------------------------------------------

    def show_overlay(
        self,
        component: Component,
        options: OverlayOptions | None = None,
    ) -> OverlayHandle:
        """Push an overlay and optionally transfer focus to it."""
        if options is None:
            options = OverlayOptions()

        self.focus_order_counter += 1
        handle = OverlayHandle(component, options, self, self.focus_order_counter)

        previous_focus = self.focused_component
        entry = _OverlayEntry(
            handle=handle,
            component=component,
            options=options,
            previous_focus=previous_focus,
        )
        self.overlay_stack.append(entry)

        if not options.non_capturing:
            self.set_focus(component)

        self.request_render()
        return handle

    def hide_overlay(self, handle: OverlayHandle | None = None) -> None:
        """Remove an overlay and restore focus.

        If *handle* is given, remove that specific overlay entry.
        Otherwise pop the topmost overlay (existing behaviour).
        """
        if not self.overlay_stack:
            return

        if handle is not None:
            entry = None
            for i, e in enumerate(self.overlay_stack):
                if e.handle is handle:
                    entry = self.overlay_stack.pop(i)
                    break
            if entry is None:
                return
        else:
            entry = self.overlay_stack.pop()

        entry.handle.hide()

        if not entry.options.non_capturing:
            self.set_focus(entry.previous_focus)

        self.request_render()

    def has_overlay(self) -> bool:
        """Return ``True`` if any visible overlay is active."""
        return any(
            not e.handle.is_hidden()
            and (e.options.visible is None or e.options.visible())
            for e in self.overlay_stack
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the terminal and schedule the first render."""
        self.stopped = False
        self.terminal.start(self._handle_input, self._handle_resize)
        self.terminal.hide_cursor()
        self.request_render()

    def stop(self) -> None:
        """Stop the TUI: move cursor to the end, restore terminal state."""
        self.stopped = True

        # Move cursor past all rendered content
        if self.max_lines_rendered > 0:
            current = self.hardware_cursor_row if self.hardware_cursor_row is not None else 0
            remaining = self.max_lines_rendered - 1 - current
            if remaining > 0:
                self.terminal.move_by(remaining)
            self.terminal.write("\n")

        self.terminal.show_cursor()
        self.terminal.stop()

    # ------------------------------------------------------------------
    # Render scheduling
    # ------------------------------------------------------------------

    def request_render(self, force: bool = False) -> None:
        """Schedule a render on the next event-loop iteration."""
        if self.stopped:
            return
        if force:
            self.previous_lines = []
            self.previous_width = -1
            self.previous_height = -1
            self.cursor_row = 0
            self.hardware_cursor_row = 0
            self.max_lines_rendered = 0
            self.previous_viewport_top = 0
        if self.render_requested:
            return
        self.render_requested = True
        try:
            loop = asyncio.get_event_loop()
            loop.call_soon(self._do_render)
        except RuntimeError:
            # No running event loop — render synchronously as fallback
            self._do_render()

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def _handle_input(self, data: str) -> None:
        if self.stopped:
            return

        for chunk in _split_stdin(data):
            self._dispatch_key(chunk)

    def _dispatch_key(self, data: str) -> None:
        # Ignore key-release events
        if is_key_release(data):
            return

        # Notify input listeners
        for listener in self._input_listeners:
            listener(data)

        # Global debug key (ctrl+shift+d) — no-op placeholder
        if matches_key(data, "ctrl+shift+d"):
            return

        # Overlay focus: send input to topmost capturing overlay
        if self.overlay_stack:
            for entry in reversed(self.overlay_stack):
                if entry.handle.is_hidden():
                    continue
                if entry.options.visible is not None and not entry.options.visible():
                    continue
                if entry.options.non_capturing:
                    continue
                if hasattr(entry.component, "handle_input"):
                    entry.component.handle_input(data)
                self.request_render()
                return

        # Forward to the focused component
        if self.focused_component is not None and hasattr(
            self.focused_component, "handle_input"
        ):
            self.focused_component.handle_input(data)

        self.request_render()

    def _handle_resize(self) -> None:
        self.request_render()

    # ------------------------------------------------------------------
    # Core render
    # ------------------------------------------------------------------

    def _do_render(self) -> None:
        self.render_requested = False
        if self.stopped:
            return

        width = self.terminal.columns
        height = self.terminal.rows

        # 1. Render all children
        lines = self.render(width)

        # 2. Composite overlays
        lines = self._composite_overlays(lines, width, height)

        # 3. Extract cursor position (strip the marker)
        cursor_pos = self._extract_cursor_position(lines, height)

        # 4. Apply line resets — ensure ANSI state is clean at end of each line
        #    Skip image lines to avoid corrupting graphics protocol sequences.
        for i, line in enumerate(lines):
            if not is_image_line(line):
                lines[i] = line + _SEGMENT_RESET

        # 5. Decide on rendering strategy
        # Matching the original pi-tui: widthChanged/heightChanged are true
        # when previousWidth is non-zero (not initial state) and differs.
        width_changed = self.previous_width != 0 and self.previous_width != width
        height_changed = self.previous_height != 0 and self.previous_height != height

        # -- fullRender helper (matches TS fullRender) --
        def full_render(clear: bool) -> None:
            buf = "\x1b[?2026h"  # begin synchronized output
            if clear:
                buf += "\x1b[2J\x1b[H\x1b[3J"  # clear screen, home, clear scrollback
            for i, line in enumerate(lines):
                if i > 0:
                    buf += "\r\n"
                buf += line
            buf += "\x1b[?2026l"  # end synchronized output
            self.terminal.write(buf)

            self.cursor_row = max(0, len(lines) - 1)
            self.hardware_cursor_row = self.cursor_row
            if clear:
                self.max_lines_rendered = len(lines)
            else:
                self.max_lines_rendered = max(self.max_lines_rendered, len(lines))
            self.previous_viewport_top = max(0, self.max_lines_rendered - height)
            if cursor_pos is not None and self.show_hardware_cursor:
                self._position_hardware_cursor(cursor_pos, len(lines))
            self.previous_lines = lines[:]
            self.previous_width = width
            self.previous_height = height

        # -- Branch logic (matches TS exactly) --

        # First render — just output without clearing
        if len(self.previous_lines or []) == 0 and not width_changed and not height_changed:
            full_render(False)
            return

        # Width or height changed — full clear + re-render
        if width_changed or height_changed:
            use_clear = True
            if self.clear_on_shrink and height_changed and not width_changed:
                use_clear = height < self.previous_height
            full_render(use_clear)
            return

        # Differential update — find changed line range
        buf: list[str] = []
        buf.append("\x1b[?2026h")  # begin synchronized output

        first_changed: int | None = None
        last_changed: int | None = None
        prev = self.previous_lines or []
        max_len = max(len(lines), len(prev))

        for i in range(max_len):
            old = prev[i] if i < len(prev) else None
            new = lines[i] if i < len(lines) else None
            if old != new:
                if first_changed is None:
                    first_changed = i
                last_changed = i

        if first_changed is not None and last_changed is not None:
            current = (
                self.hardware_cursor_row if self.hardware_cursor_row is not None else 0
            )
            delta = first_changed - current
            if delta > 0:
                buf.append(f"\x1b[{delta}B")
            elif delta < 0:
                buf.append(f"\x1b[{-delta}A")

            for i in range(first_changed, last_changed + 1):
                if i > first_changed:
                    buf.append("\n")
                buf.append("\r")
                buf.append("\x1b[2K")
                if i < len(lines):
                    buf.append(lines[i])

            actual_end = last_changed

            if len(lines) < len(prev):
                for i in range(last_changed + 1, len(prev)):
                    buf.append("\n")
                    buf.append("\r")
                    buf.append("\x1b[2K")
                    actual_end = i

            self.hardware_cursor_row = actual_end
            self.max_lines_rendered = max(len(lines), self.max_lines_rendered)

        # Position hardware cursor for IME input
        if cursor_pos is not None and self.show_hardware_cursor:
            self._position_hardware_cursor_buf(buf, cursor_pos, len(lines))

        buf.append("\x1b[?2026l")  # end synchronized output

        self.previous_lines = lines[:]
        self.previous_width = width
        self.previous_height = height

        self.terminal.write("".join(buf))

    # ------------------------------------------------------------------
    # Overlay compositing
    # ------------------------------------------------------------------

    def _composite_overlays(
        self,
        lines: list[str],
        term_width: int,
        term_height: int,
    ) -> list[str]:
        """Render each visible overlay and splice it into *lines*."""
        if not self.overlay_stack:
            return lines

        result = lines[:]

        for entry in self.overlay_stack:
            if entry.handle.is_hidden():
                continue
            if entry.options.visible is not None and not entry.options.visible():
                continue

            # Render the overlay component
            overlay_width = self._resolve_size_value(
                entry.options.width, term_width
            )
            if overlay_width is None:
                overlay_width = term_width
            if entry.options.min_width is not None:
                overlay_width = max(overlay_width, entry.options.min_width)
            overlay_width = min(overlay_width, term_width)

            overlay_lines = entry.component.render(overlay_width)
            if not overlay_lines:
                continue

            # Apply max_height
            max_h = self._resolve_size_value(entry.options.max_height, term_height)
            if max_h is not None and len(overlay_lines) > max_h:
                overlay_lines = overlay_lines[:max_h]

            overlay_height = len(overlay_lines)

            # Resolve layout position
            start_row, start_col = self._resolve_overlay_layout(
                entry.options, overlay_height, overlay_width, term_width, term_height,
            )

            # Ensure the base content has enough lines
            while len(result) < start_row + overlay_height:
                result.append("")

            # Splice each overlay line into the result
            for i, overlay_line in enumerate(overlay_lines):
                row = start_row + i
                if 0 <= row < len(result):
                    result[row] = self._composite_line_at(
                        result[row],
                        overlay_line,
                        start_col,
                        overlay_width,
                        term_width,
                    )

        return result

    def _resolve_overlay_layout(
        self,
        options: OverlayOptions,
        overlay_height: int,
        overlay_width: int,
        term_width: int,
        term_height: int,
    ) -> tuple[int, int]:
        """Return ``(start_row, start_col)`` for an overlay."""
        margin = self._normalise_margin(options.margin)

        usable_width = term_width - margin.left - margin.right
        usable_height = term_height - margin.top - margin.bottom

        # Explicit row/col
        if options.row is not None and options.col is not None:
            row = self._resolve_size_value(options.row, term_height) or 0
            col = self._resolve_size_value(options.col, term_width) or 0
            return (
                row + options.offset_y,
                col + options.offset_x,
            )

        anchor = options.anchor

        # Row
        if anchor in ("top-left", "top-right", "top-center"):
            row = margin.top
        elif anchor in ("bottom-left", "bottom-right", "bottom-center"):
            row = max(0, margin.top + usable_height - overlay_height)
        else:  # center variants
            row = margin.top + max(0, (usable_height - overlay_height) // 2)

        # Col
        if anchor in ("top-left", "bottom-left", "center-left"):
            col = margin.left
        elif anchor in ("top-right", "bottom-right", "center-right"):
            col = max(0, margin.left + usable_width - overlay_width)
        else:  # center variants
            col = margin.left + max(0, (usable_width - overlay_width) // 2)

        return (
            row + options.offset_y,
            col + options.offset_x,
        )

    @staticmethod
    def _normalise_margin(margin: OverlayMargin | int | None) -> OverlayMargin:
        if margin is None:
            return OverlayMargin()
        if isinstance(margin, int):
            return OverlayMargin(top=margin, right=margin, bottom=margin, left=margin)
        return margin

    @staticmethod
    def _resolve_size_value(value: SizeValue | None, reference: int) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.endswith("%"):
            try:
                pct = float(value[:-1])
                return int(reference * pct / 100)
            except ValueError:
                return None
        return None

    def _composite_line_at(
        self,
        base_line: str,
        overlay_line: str,
        start_col: int,
        overlay_width: int,
        total_width: int,
    ) -> str:
        """Splice *overlay_line* into *base_line* at column *start_col*."""
        if is_image_line(base_line):
            return base_line

        if start_col < 0:
            start_col = 0

        base_width = visible_width(base_line)

        # Pad base if it's too short
        if base_width < start_col + overlay_width:
            pad_needed = start_col + overlay_width - base_width
            base_line = base_line + " " * pad_needed

        # Extract before / after segments from the base line
        after_start = start_col + overlay_width
        after_len = max(0, total_width - after_start)

        segments = extract_segments(
            base_line,
            before_end=start_col,
            after_start=after_start,
            after_len=after_len,
            strict_after=True,
        )

        before = segments["before"]
        before_width = segments["before_width"]
        after = segments["after"]

        # Pad before segment to reach start_col
        if before_width < start_col:
            before = str(before) + " " * (start_col - int(before_width))

        # Pad overlay to fill its width
        ov_width = visible_width(overlay_line)
        if ov_width < overlay_width:
            overlay_line = overlay_line + " " * (overlay_width - ov_width)

        return str(before) + overlay_line + str(after)

    # ------------------------------------------------------------------
    # Cursor extraction
    # ------------------------------------------------------------------

    def _extract_cursor_position(
        self,
        lines: list[str],
        height: int,
    ) -> tuple[int, int] | None:
        """Find ``CURSOR_MARKER`` in *lines*, strip it, return ``(row, col)``."""
        for row_idx, line in enumerate(lines):
            marker_pos = line.find(CURSOR_MARKER)
            if marker_pos == -1:
                continue
            # Column = visible width of content before the marker
            prefix = line[:marker_pos]
            col = visible_width(prefix)
            # Strip the marker
            lines[row_idx] = line[:marker_pos] + line[marker_pos + len(CURSOR_MARKER):]
            return (row_idx, col)
        return None

    # ------------------------------------------------------------------
    # Hardware cursor positioning (for IME)
    # ------------------------------------------------------------------

    def _position_hardware_cursor_buf(
        self,
        buf: list[str],
        cursor_pos: tuple[int, int],
        total_lines: int,
    ) -> None:
        """Append escape sequences to *buf* to position the hardware cursor."""
        target_row, target_col = cursor_pos

        # Move from current hardware cursor row to the target row
        current = self.hardware_cursor_row if self.hardware_cursor_row is not None else (
            total_lines - 1
        )
        delta = target_row - current
        if delta > 0:
            buf.append(f"\x1b[{delta}B")
        elif delta < 0:
            buf.append(f"\x1b[{-delta}A")

        # Move to column (1-indexed in ANSI)
        buf.append(f"\r\x1b[{target_col}C")

        # Keep hardware cursor hidden — components render a fake (inverse-video)
        # cursor themselves.  Showing the terminal cursor here causes a doubled
        # cursor artifact and intermittent disappearance during differential
        # redraws.  The cursor position is still set so that IME overlays
        # appear at the correct location.
        buf.append("\x1b[?25l")

        self.hardware_cursor_row = target_row
        self.cursor_row = target_row

    def _position_hardware_cursor(
        self,
        cursor_pos: tuple[int, int],
        total_lines: int,
    ) -> None:
        """Position the terminal cursor for IME (immediate write variant)."""
        buf: list[str] = []
        self._position_hardware_cursor_buf(buf, cursor_pos, total_lines)
        self.terminal.write("".join(buf))
