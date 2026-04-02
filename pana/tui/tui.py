"""TUI core engine with differential rendering and overlay system.

Provides a Component protocol, Container, overlay management, and the main
TUI class that drives the render loop against a Terminal backend.

Mirrors the pi-tui TypeScript TUI class (MIT License).
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pana.tui.ansi import ANSI
from pana.tui.keys import is_key_release, matches_key
from pana.tui.terminal import Terminal
from pana.tui.terminal_image import (
    CellDimensions,
    get_capabilities,
    is_image_line,
    set_cell_dimensions,
)
from pana.tui.utils import extract_segments, slice_by_column, slice_with_width, visible_width

logger = logging.getLogger(__name__)




@runtime_checkable
class Component(Protocol):
    def render(self, width: int) -> list[str]: ...
    def invalidate(self) -> None: ...


@runtime_checkable
class Focusable(Protocol):
    focused: bool


def is_focusable(component: object) -> bool:
    return isinstance(component, Focusable)




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
            child.invalidate()

    def render(self, width: int) -> list[str]:
        lines: list[str] = []
        for child in self.children:
            lines.extend(child.render(width))
        return lines



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
    # visible() receives (columns, rows) and returns True if overlay should render
    visible: Callable[[int, int], bool] | None = None
    non_capturing: bool = False




class OverlayHandle:
    """Handle for controlling a shown overlay.

    Methods mirror the JS OverlayHandle interface exactly:
        hide()            – remove overlay from stack, restore focus.
        set_hidden(bool)  – toggle visibility without removing.
        is_hidden()
        focus()           – transfer focus to this overlay.
        unfocus()         – give focus back to the previous owner.
        is_focused()      – True iff TUI.focusedComponent is this component.
    """

    def __init__(
        self,
        component: Component,
        options: OverlayOptions,
        tui: "TUI",
        focus_order: int,
    ) -> None:
        self.component = component
        self.options = options
        self._tui = tui
        self._hidden = False
        self.focus_order = focus_order

    def hide(self) -> None:
        """Remove this overlay from the stack and restore focus."""
        self._tui.hide_overlay(self)

    def set_hidden(self, hidden: bool) -> None:
        if self._hidden == hidden:
            return
        self._hidden = hidden
        if hidden:
            # If this overlay currently holds focus, move to next visible or preFocus
            entry = self._tui._get_entry_for_handle(self)
            if entry and self._tui.focused_component is self.component:
                top = self._tui.get_topmost_visible_overlay()
                self._tui.set_focus(
                    top.component if top else (entry.previous_focus)
                )
        else:
            # Restore focus to this overlay when un-hiding
            if not self.options.non_capturing and self._tui._is_overlay_visible_for_handle(self):
                self.focus_order = self._tui._next_focus_order()
                self._tui.set_focus(self.component)
        self._tui.request_render()

    def is_hidden(self) -> bool:
        return self._hidden

    def focus(self) -> None:
        entry = self._tui._get_entry_for_handle(self)
        if not entry or not self._tui._is_overlay_visible_for_handle(self):
            return
        if self._tui.focused_component is not self.component:
            self._tui.set_focus(self.component)
        self.focus_order = self._tui._next_focus_order()
        self._tui.request_render()

    def unfocus(self) -> None:
        if self._tui.focused_component is not self.component:
            return
        entry = self._tui._get_entry_for_handle(self)
        top = self._tui.get_topmost_visible_overlay()
        if top and top.component is not self.component:
            self._tui.set_focus(top.component)
        elif entry:
            self._tui.set_focus(entry.previous_focus)
        self._tui.request_render()

    def is_focused(self) -> bool:
        """Return True iff this overlay's component currently holds TUI keyboard focus.

        Mirrors JS: isFocused: () => this.focusedComponent === component
        """
        return self._tui.focused_component is self.component




@dataclass
class _OverlayEntry:
    handle: OverlayHandle
    component: Component
    options: OverlayOptions
    previous_focus: Component | None = None




@dataclass
class _OverlayLayout:
    row: int
    col: int
    width: int
    max_height: int | None




class TUI(Container):
    """Main TUI engine with differential rendering and overlay support.

    Environment variables (mirroring pi-tui TypeScript):
        PI_HARDWARE_CURSOR   – set to "1" to show the hardware terminal cursor.
        PI_CLEAR_ON_SHRINK   – set to "1" to full-clear when content shrinks.
        PI_DEBUG_REDRAW      – set to "1" to log full-render reasons.
        PI_TUI_DEBUG         – set to "1" to write per-render debug logs to /tmp/tui/.
    """

    def __init__(self, terminal: Terminal, show_hardware_cursor: bool | None = None) -> None:
        super().__init__()
        self.terminal = terminal

        # Render state
        self._previous_lines: list[str] = []
        self._previous_width: int = 0
        self._previous_height: int = 0
        self.focused_component: Component | None = None
        self._render_requested: bool = False
        self._cursor_row: int = 0
        self._hardware_cursor_row: int = 0
        self._max_lines_rendered: int = 0
        self._previous_viewport_top: int = 0
        self._full_redraw_count: int = 0

        # Cell-size query (for image rendering)
        self._input_buffer: str = ""
        self._cell_size_query_pending: bool = False

        # Config flags (env-var driven, matching TS)
        self.show_hardware_cursor: bool = (
            show_hardware_cursor
            if show_hardware_cursor is not None
            else os.environ.get("PI_HARDWARE_CURSOR") == "1"
        )
        self.clear_on_shrink: bool = os.environ.get("PI_CLEAR_ON_SHRINK") == "1"

        # Overlay system
        self._overlay_stack: list[_OverlayEntry] = []
        self._focus_order_counter: int = 0

        # Input listeners — each may return {"consume": True} or {"data": "..."}
        # Listeners may be sync or async; async ones are awaited in _dispatch_key.
        self._input_listeners: list[
            Callable[[str], Awaitable[dict | None] | dict | None]
        ] = []

        # Debug callbacks
        self.on_debug: Callable[[], None] | None = None

        self.stopped: bool = False


    @property
    def previous_lines(self) -> list[str]:
        return self._previous_lines

    @property
    def previous_width(self) -> int:
        return self._previous_width

    @property
    def previous_height(self) -> int:
        return self._previous_height

    @property
    def max_lines_rendered(self) -> int:
        return self._max_lines_rendered

    @property
    def hardware_cursor_row(self) -> int:
        return self._hardware_cursor_row

    @hardware_cursor_row.setter
    def hardware_cursor_row(self, value: int) -> None:
        self._hardware_cursor_row = value

    @property
    def overlay_stack(self) -> list[_OverlayEntry]:
        return self._overlay_stack

    @property
    def full_redraws(self) -> int:
        return self._full_redraw_count


    def get_show_hardware_cursor(self) -> bool:
        return self.show_hardware_cursor

    def set_show_hardware_cursor(self, enabled: bool) -> None:
        if self.show_hardware_cursor == enabled:
            return
        self.show_hardware_cursor = enabled
        if not enabled:
            self.terminal.hide_cursor()
        self.request_render()

    def get_clear_on_shrink(self) -> bool:
        return self.clear_on_shrink

    def set_clear_on_shrink(self, enabled: bool) -> None:
        self.clear_on_shrink = enabled


    def set_focus(self, component: Component | None) -> None:
        if self.focused_component is not None and is_focusable(self.focused_component):
            self.focused_component.focused = False
        self.focused_component = component
        if component is not None and is_focusable(component):
            component.focused = True


    def add_input_listener(
        self, listener: Callable[[str], Awaitable[dict | None] | dict | None]
    ) -> Callable[[], None]:
        """Register *listener* and return a cleanup callable.

        A listener receives the raw input data and may return:
          None              – pass through unchanged.
          {"consume": True} – stop dispatching this event entirely.
          {"data": "..."}   – replace the data for subsequent listeners.

        Listeners may be either sync or async.  Async listeners (those whose
        return value is a coroutine) are automatically awaited before the
        result is inspected.
        """
        self._input_listeners.append(listener)

        def _remove() -> None:
            try:
                self._input_listeners.remove(listener)
            except ValueError:
                pass

        return _remove

    def remove_input_listener(
        self, listener: Callable[[str], Awaitable[dict | None] | dict | None]
    ) -> None:
        try:
            self._input_listeners.remove(listener)
        except ValueError:
            pass


    def _next_focus_order(self) -> int:
        self._focus_order_counter += 1
        return self._focus_order_counter

    def _get_entry_for_handle(self, handle: OverlayHandle) -> _OverlayEntry | None:
        for e in self._overlay_stack:
            if e.handle is handle:
                return e
        return None

    def _is_overlay_visible_for_handle(self, handle: OverlayHandle) -> bool:
        entry = self._get_entry_for_handle(handle)
        if entry is None:
            return False
        return self._is_overlay_visible(entry)

    def _is_overlay_visible(self, entry: _OverlayEntry) -> bool:
        if entry.handle.is_hidden():
            return False
        if entry.options.visible is not None:
            return entry.options.visible(self.terminal.columns, self.terminal.rows)
        return True

    def get_topmost_visible_overlay(self) -> _OverlayEntry | None:
        """Return the topmost visible non-capturing overlay entry, if any."""
        for entry in reversed(self._overlay_stack):
            if entry.options.non_capturing:
                continue
            if self._is_overlay_visible(entry):
                return entry
        return None

    def show_overlay(
        self,
        component: Component,
        options: OverlayOptions | None = None,
    ) -> OverlayHandle:
        """Push an overlay and optionally transfer focus to it."""
        if options is None:
            options = OverlayOptions()

        fo = self._next_focus_order()
        handle = OverlayHandle(component, options, self, fo)
        entry = _OverlayEntry(
            handle=handle,
            component=component,
            options=options,
            previous_focus=self.focused_component,
        )
        self._overlay_stack.append(entry)

        if not options.non_capturing and self._is_overlay_visible(entry):
            self.set_focus(component)

        self.terminal.hide_cursor()
        self.request_render()
        return handle

    def hide_overlay(self, handle: OverlayHandle | None = None) -> None:
        """Remove an overlay from the stack and restore focus.

        If *handle* is given, remove that specific overlay; otherwise pop the
        topmost overlay (matching the original JS ``hideOverlay()`` behaviour).
        """
        if not self._overlay_stack:
            return

        if handle is not None:
            entry = None
            for i, e in enumerate(self._overlay_stack):
                if e.handle is handle:
                    entry = self._overlay_stack.pop(i)
                    break
            if entry is None:
                return
        else:
            entry = self._overlay_stack.pop()

        entry.handle._hidden = True  # mark as hidden so callers see it

        if self.focused_component is entry.component:
            top = self.get_topmost_visible_overlay()
            self.set_focus(top.component if top else entry.previous_focus)

        if not self._overlay_stack:
            self.terminal.hide_cursor()

        self.request_render()

    def has_overlay(self) -> bool:
        return any(self._is_overlay_visible(e) for e in self._overlay_stack)


    def query_cell_size(self) -> None:
        """Send CSI 16 t to query cell dimensions in pixels.

        Only sent when the terminal reports image capability — the response
        (CSI 6 ; height ; width t) is parsed in _handle_input and used to
        call set_cell_dimensions() so images can calculate row counts
        accurately.
        """
        if not get_capabilities().images:
            return
        self._cell_size_query_pending = True
        self.terminal.write(ANSI.CELL_SIZE_QUERY)

    def _parse_cell_size_response(self) -> str:
        """Parse cell-size response from _input_buffer; return remaining data."""
        import re
        response_re = re.compile(r"\x1b\[6;(\d+);(\d+)t")
        m = response_re.search(self._input_buffer)
        if m:
            height_px = int(m.group(1))
            width_px = int(m.group(2))
            if height_px > 0 and width_px > 0:
                set_cell_dimensions(CellDimensions(width_px=width_px, height_px=height_px))
                self.invalidate()
                self.request_render()
            self._input_buffer = response_re.sub("", self._input_buffer, count=1)
            self._cell_size_query_pending = False

        # If buffer ends with what looks like an incomplete cell-size response,
        # hold back and wait for more data.
        partial_re = re.compile(r"\x1b(\[6?;?[\d;]*)?$")
        if partial_re.search(self._input_buffer):
            last = self._input_buffer[-1] if self._input_buffer else ""
            if not (last.isalpha() or last == "~"):
                return ""  # not yet complete — keep buffering

        result = self._input_buffer
        self._input_buffer = ""
        self._cell_size_query_pending = False
        return result


    def invalidate(self) -> None:
        super().invalidate()
        for entry in self._overlay_stack:
            entry.component.invalidate()

    def _init(self) -> None:
        """Synchronous setup: raw-mode terminal, cursor, cell-size query, first render."""
        self.stopped = False
        self.terminal.start(self._handle_resize)
        self.terminal.hide_cursor()
        self.query_cell_size()
        self.request_render()

    async def start(self) -> None:
        """Start the TUI and block until stop() is called."""
        self._init()
        await self.terminal.run(self._handle_input)

    def stop(self) -> None:
        self.stopped = True
        if self._previous_lines:
            # Move cursor to one line past the last content line
            target_row = len(self._previous_lines)
            line_diff = target_row - self._hardware_cursor_row
            if line_diff > 0:
                self.terminal.write(ANSI.cursor_down(line_diff))
            elif line_diff < 0:
                self.terminal.write(ANSI.cursor_up(-line_diff))
            self.terminal.write("\r\n")
        self.terminal.show_cursor()
        self.terminal.stop()


    def request_render(self, force: bool = False) -> None:
        if self.stopped:
            return
        if force:
            self._previous_lines = []
            self._previous_width = -1
            self._previous_height = -1
            self._cursor_row = 0
            self._hardware_cursor_row = 0
            self._max_lines_rendered = 0
            self._previous_viewport_top = 0
        if self._render_requested:
            return
        self._render_requested = True
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon(self._do_render)
        except RuntimeError:
            self._do_render()


    async def _handle_input(self, data: str) -> None:
        if self.stopped:
            return
        await self._dispatch_key(data)

    async def _dispatch_key(self, data: str) -> None:
        # Input-listener pipeline: listeners may transform or consume events
        if self._input_listeners:
            current = data
            for listener in list(self._input_listeners):
                result = listener(current)
                if asyncio.iscoroutine(result):
                    result = await result
                if result:
                    if result.get("consume"):
                        return
                    if "data" in result:
                        current = result["data"]
            if not current:
                return
            data = current

        # Cell-size response buffering
        if self._cell_size_query_pending:
            self._input_buffer += data
            filtered = self._parse_cell_size_response()
            if not filtered:
                return
            data = filtered

        # Ignore key-release events (Kitty protocol)
        if is_key_release(data):
            return

        # Global debug key (Shift+Ctrl+D)
        if matches_key(data, "shift+ctrl+d") and self.on_debug:
            self.on_debug()
            return

        # Overlay focus: check whether focused overlay is still visible
        focused_overlay = next(
            (e for e in self._overlay_stack if e.component is self.focused_component),
            None,
        )
        if focused_overlay and not self._is_overlay_visible(focused_overlay):
            top = self.get_topmost_visible_overlay()
            if top:
                self.set_focus(top.component)
            else:
                self.set_focus(focused_overlay.previous_focus)

        # Forward to focused component
        if self.focused_component is not None and hasattr(
            self.focused_component, "handle_input"
        ):
            # Respect wantsKeyRelease flag (opt-in for release events)
            if is_key_release(data) and not getattr(
                self.focused_component, "wants_key_release", False
            ):
                return
            await self.focused_component.handle_input(data)  # type: ignore[union-attr]

        self.request_render()

    def _handle_resize(self) -> None:
        self.request_render()


    @staticmethod
    def _is_termux_session() -> bool:
        return bool(os.environ.get("TERMUX_VERSION"))

    def _log_redraw(self, reason: str) -> None:
        if os.environ.get("PI_DEBUG_REDRAW") != "1":
            return
        log_path = pathlib.Path.home() / ".pi" / "agent" / "pi-debug.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        import datetime
        msg = (
            f"[{datetime.datetime.now().isoformat()}] fullRender: {reason} "
            f"(prev={len(self._previous_lines)}, new lines pending, "
            f"prevW={self._previous_width}, prevH={self._previous_height})\n"
        )
        try:
            log_path.open("a").write(msg)
        except OSError:
            pass

    def _write_crash_log(self, new_lines: list[str], bad_idx: int, term_width: int) -> None:
        try:
            crash_path = pathlib.Path.home() / ".pi" / "agent" / "pi-crash.log"
            crash_path.parent.mkdir(parents=True, exist_ok=True)
            import datetime
            lines_dump = "\n".join(
                f"[{i}] (w={visible_width(l)}) {l}" for i, l in enumerate(new_lines)
            )
            crash_path.write_text(
                f"Crash at {datetime.datetime.now().isoformat()}\n"
                f"Terminal width: {term_width}\n"
                f"Line {bad_idx} visible width: {visible_width(new_lines[bad_idx])}\n\n"
                f"=== All rendered lines ===\n{lines_dump}\n",
                encoding="utf-8",
            )
        except OSError:
            pass


    def _do_render(self) -> None:
        self._render_requested = False
        if self.stopped:
            return

        width = self.terminal.columns
        height = self.terminal.rows

        # Local viewport variables (may be mutated during render)
        viewport_top = max(0, self._max_lines_rendered - height)
        prev_viewport_top = self._previous_viewport_top
        hw_cursor = self._hardware_cursor_row  # local mutable copy

        def compute_line_diff(target_row: int) -> int:
            current_screen_row = hw_cursor - prev_viewport_top
            target_screen_row = target_row - viewport_top
            return target_screen_row - current_screen_row

        # 1. Render all children
        new_lines = self.render(width)

        # 2. Composite overlays
        if self._overlay_stack:
            new_lines = self._composite_overlays(new_lines, width, height)

        # 3. Extract cursor position (strips marker from lines)
        cursor_pos = self._extract_cursor_position(new_lines, height)

        # 4. Apply line resets
        new_lines = self._apply_line_resets(new_lines)

        # 5. Decide rendering strategy
        width_changed = self._previous_width != 0 and self._previous_width != width
        height_changed = self._previous_height != 0 and self._previous_height != height

        def full_render(clear: bool) -> None:
            nonlocal hw_cursor, viewport_top, prev_viewport_top
            self._full_redraw_count += 1
            buf = ANSI.SYNC_START
            if clear:
                buf += ANSI.CLEAR_SCREEN + ANSI.CLEAR_SCROLLBACK
            for i, line in enumerate(new_lines):
                if i > 0:
                    buf += "\r\n"
                buf += line
            buf += ANSI.SYNC_END
            self.terminal.write(buf)
            self._cursor_row = max(0, len(new_lines) - 1)
            self._hardware_cursor_row = self._cursor_row
            hw_cursor = self._hardware_cursor_row
            if clear:
                self._max_lines_rendered = len(new_lines)
            else:
                self._max_lines_rendered = max(self._max_lines_rendered, len(new_lines))
            self._previous_viewport_top = max(0, self._max_lines_rendered - height)
            viewport_top = self._previous_viewport_top
            prev_viewport_top = self._previous_viewport_top
            self._position_hardware_cursor(cursor_pos, len(new_lines))
            self._previous_lines = list(new_lines)
            self._previous_width = width
            self._previous_height = height

        # First render — output without clearing (assumes clean screen)
        if not self._previous_lines and not width_changed and not height_changed:
            self._log_redraw("first render")
            full_render(False)
            return

        # Width changed — wrapping changes, full re-render
        if width_changed:
            self._log_redraw(f"terminal width changed ({self._previous_width} -> {width})")
            full_render(True)
            return

        # Height changed (Termux special-case: keyboard toggles change height;
        # avoid replaying full history on every toggle)
        if height_changed and not self._is_termux_session():
            self._log_redraw(f"terminal height changed ({self._previous_height} -> {height})")
            full_render(True)
            return

        # clearOnShrink — clear empty rows when content shrinks (only without overlays)
        if (
            self.clear_on_shrink
            and len(new_lines) < self._max_lines_rendered
            and not self._overlay_stack
        ):
            self._log_redraw(f"clearOnShrink (maxLinesRendered={self._max_lines_rendered})")
            full_render(True)
            return

        # --- Find first / last changed line ---
        first_changed = -1
        last_changed = -1
        max_len = max(len(new_lines), len(self._previous_lines))

        for i in range(max_len):
            old = self._previous_lines[i] if i < len(self._previous_lines) else ""
            new = new_lines[i] if i < len(new_lines) else ""
            if old != new:
                if first_changed == -1:
                    first_changed = i
                last_changed = i

        # Appended lines: all new lines at the bottom count as changed
        appended_lines = len(new_lines) > len(self._previous_lines)
        if appended_lines:
            if first_changed == -1:
                first_changed = len(self._previous_lines)
            last_changed = len(new_lines) - 1

        # Optimised path: only new lines appended at the very end
        append_start = (
            appended_lines
            and first_changed == len(self._previous_lines)
            and first_changed > 0
        )

        # No changes at all
        if first_changed == -1:
            self._position_hardware_cursor(cursor_pos, len(new_lines))
            self._previous_viewport_top = max(0, self._max_lines_rendered - height)
            self._previous_height = height
            return

        # All changes are in deleted lines — nothing new to render, just clear
        if first_changed >= len(new_lines):
            if len(self._previous_lines) > len(new_lines):
                buf = ANSI.SYNC_START
                target_row = max(0, len(new_lines) - 1)
                line_diff = compute_line_diff(target_row)
                if line_diff > 0:
                    buf += ANSI.cursor_down(line_diff)
                elif line_diff < 0:
                    buf += ANSI.cursor_up(-line_diff)
                buf += "\r"
                extra_lines = len(self._previous_lines) - len(new_lines)
                if extra_lines > height:
                    self._log_redraw(f"extraLines > height ({extra_lines} > {height})")
                    full_render(True)
                    return
                if extra_lines > 0:
                    buf += ANSI.cursor_down(1)
                for i in range(extra_lines):
                    buf += "\r" + ANSI.CLEAR_FULL_LINE
                    if i < extra_lines - 1:
                        buf += ANSI.cursor_down(1)
                if extra_lines > 0:
                    buf += ANSI.cursor_up(extra_lines)
                buf += ANSI.SYNC_END
                self.terminal.write(buf)
                self._cursor_row = target_row
                self._hardware_cursor_row = target_row
            self._position_hardware_cursor(cursor_pos, len(new_lines))
            self._previous_lines = list(new_lines)
            self._previous_width = width
            self._previous_height = height
            self._previous_viewport_top = max(0, self._max_lines_rendered - height)
            return

        # First change is above previous visible viewport → full re-render
        prev_content_viewport_top = max(0, len(self._previous_lines) - height)
        if first_changed < prev_content_viewport_top:
            self._log_redraw(
                f"firstChanged < viewportTop ({first_changed} < {prev_content_viewport_top})"
            )
            full_render(True)
            return

        # --- Differential update ---
        buf = ANSI.SYNC_START
        prev_viewport_bottom = prev_viewport_top + height - 1
        move_target_row = first_changed - 1 if append_start else first_changed

        # Scroll terminal if target is below visible area
        if move_target_row > prev_viewport_bottom:
            current_screen_row = max(0, min(height - 1, hw_cursor - prev_viewport_top))
            move_to_bottom = height - 1 - current_screen_row
            if move_to_bottom > 0:
                buf += ANSI.cursor_down(move_to_bottom)
            scroll = move_target_row - prev_viewport_bottom
            buf += "\r\n" * scroll
            prev_viewport_top += scroll
            viewport_top += scroll
            hw_cursor = move_target_row

        line_diff = compute_line_diff(move_target_row)
        if line_diff > 0:
            buf += ANSI.cursor_down(line_diff)
        elif line_diff < 0:
            buf += ANSI.cursor_up(-line_diff)
        buf += "\r\n" if append_start else "\r"

        render_end = min(last_changed, len(new_lines) - 1)
        for i in range(first_changed, render_end + 1):
            if i > first_changed:
                buf += "\r\n"
            buf += ANSI.CLEAR_FULL_LINE
            line = new_lines[i]
            # Crash protection: a line wider than the terminal would corrupt the display
            if not is_image_line(line) and visible_width(line) > width:
                self._write_crash_log(new_lines, i, width)
                self.stop()
                raise RuntimeError(
                    f"Rendered line {i} exceeds terminal width "
                    f"({visible_width(line)} > {width}).\n"
                    "This is likely caused by a custom component not truncating its output.\n"
                    "Use visible_width() to measure and truncate_to_width() to truncate lines.\n"
                    f"Debug log written to: {pathlib.Path.home() / '.pi' / 'agent' / 'pi-crash.log'}"
                )
            buf += line

        final_cursor_row = render_end

        # Clear lines that existed before but are now gone
        if len(self._previous_lines) > len(new_lines):
            if render_end < len(new_lines) - 1:
                move_down = len(new_lines) - 1 - render_end
                buf += ANSI.cursor_down(move_down)
                final_cursor_row = len(new_lines) - 1
            extra_lines = len(self._previous_lines) - len(new_lines)
            for _ in range(extra_lines):
                buf += "\r\n" + ANSI.CLEAR_FULL_LINE
            buf += ANSI.cursor_up(extra_lines)

        buf += ANSI.SYNC_END
        self.terminal.write(buf)

        self._cursor_row = max(0, len(new_lines) - 1)
        self._hardware_cursor_row = final_cursor_row
        self._max_lines_rendered = max(self._max_lines_rendered, len(new_lines))
        self._previous_viewport_top = max(0, self._max_lines_rendered - height)
        self._position_hardware_cursor(cursor_pos, len(new_lines))
        self._previous_lines = list(new_lines)
        self._previous_width = width
        self._previous_height = height


    def _apply_line_resets(self, lines: list[str]) -> list[str]:
        reset = ANSI.SEGMENT_RESET
        for i, line in enumerate(lines):
            if not is_image_line(line):
                lines[i] = line + reset
        return lines


    def _resolve_size_value(self, value: SizeValue | None, reference: int) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.endswith("%"):
            try:
                return int(reference * float(value[:-1]) / 100)
            except ValueError:
                return None
        return None

    def _resolve_overlay_layout(
        self,
        options: OverlayOptions,
        overlay_height: int,
        term_width: int,
        term_height: int,
    ) -> _OverlayLayout:
        margin = self._normalise_margin(options.margin)
        mt = max(0, margin.top)
        mr = max(0, margin.right)
        mb = max(0, margin.bottom)
        ml = max(0, margin.left)

        avail_w = max(1, term_width - ml - mr)
        avail_h = max(1, term_height - mt - mb)

        # Width
        ov_width = self._resolve_size_value(options.width, term_width) or min(80, avail_w)
        if options.min_width is not None:
            ov_width = max(ov_width, options.min_width)
        ov_width = max(1, min(ov_width, avail_w))

        # Max height
        max_h = self._resolve_size_value(options.max_height, term_height)
        if max_h is not None:
            max_h = max(1, min(max_h, avail_h))

        effective_h = min(overlay_height, max_h) if max_h is not None else overlay_height

        # Row
        if options.row is not None:
            rv = self._resolve_size_value(options.row, term_height)
            if rv is None:
                row = self._anchor_row("center", effective_h, avail_h, mt)
            else:
                row = rv
        else:
            row = self._anchor_row(options.anchor, effective_h, avail_h, mt)

        # Col
        if options.col is not None:
            cv = self._resolve_size_value(options.col, term_width)
            if cv is None:
                col = self._anchor_col("center", ov_width, avail_w, ml)
            else:
                col = cv
        else:
            col = self._anchor_col(options.anchor, ov_width, avail_w, ml)

        # Offsets
        row += options.offset_y
        col += options.offset_x

        # Clamp to bounds
        row = max(mt, min(row, term_height - mb - effective_h))
        col = max(ml, min(col, term_width - mr - ov_width))

        return _OverlayLayout(row=row, col=col, width=ov_width, max_height=max_h)

    @staticmethod
    def _anchor_row(anchor: str, height: int, avail: int, margin_top: int) -> int:
        if anchor in ("top-left", "top-center", "top-right"):
            return margin_top
        if anchor in ("bottom-left", "bottom-center", "bottom-right"):
            return margin_top + avail - height
        return margin_top + max(0, (avail - height) // 2)

    @staticmethod
    def _anchor_col(anchor: str, width: int, avail: int, margin_left: int) -> int:
        if anchor in ("top-left", "left-center", "bottom-left"):
            return margin_left
        if anchor in ("top-right", "right-center", "bottom-right"):
            return margin_left + avail - width
        return margin_left + max(0, (avail - width) // 2)

    @staticmethod
    def _normalise_margin(margin: OverlayMargin | int | None) -> OverlayMargin:
        if margin is None:
            return OverlayMargin()
        if isinstance(margin, int):
            return OverlayMargin(top=margin, right=margin, bottom=margin, left=margin)
        return margin

    def _composite_overlays(
        self,
        lines: list[str],
        term_width: int,
        term_height: int,
    ) -> list[str]:
        """Render each visible overlay and composite it into *lines*."""
        if not self._overlay_stack:
            return lines

        result = list(lines)

        # Collect visible entries sorted by focus_order (lower = behind)
        visible_entries = [
            e for e in self._overlay_stack if self._is_overlay_visible(e)
        ]
        visible_entries.sort(key=lambda e: e.handle.focus_order)

        rendered: list[tuple[list[str], int, int, int]] = []  # (overlayLines, row, col, width)
        min_lines_needed = len(result)

        for entry in visible_entries:
            # Phase 1: determine width and max_height (pass height=0)
            layout0 = self._resolve_overlay_layout(entry.options, 0, term_width, term_height)
            overlay_lines = entry.component.render(layout0.width)
            if not overlay_lines:
                continue

            # Apply max_height
            if layout0.max_height is not None and len(overlay_lines) > layout0.max_height:
                overlay_lines = overlay_lines[: layout0.max_height]

            # Phase 2: get final row/col with actual height
            layout = self._resolve_overlay_layout(
                entry.options, len(overlay_lines), term_width, term_height
            )
            rendered.append((overlay_lines, layout.row, layout.col, layout.width))
            min_lines_needed = max(min_lines_needed, layout.row + len(overlay_lines))

        # Pad result to the working area (max of ever-rendered and overlay requirements)
        working_height = max(self._max_lines_rendered, min_lines_needed)
        while len(result) < working_height:
            result.append("")

        # viewport_start: offset into result where the visible viewport begins
        viewport_start = max(0, working_height - term_height)

        for overlay_lines, row, col, ov_width in rendered:
            for i, overlay_line in enumerate(overlay_lines):
                idx = viewport_start + row + i
                if 0 <= idx < len(result):
                    # Defensive truncation of overlay line to declared width
                    if visible_width(overlay_line) > ov_width:
                        overlay_line = slice_by_column(overlay_line, 0, ov_width, True)
                    result[idx] = self._composite_line_at(
                        result[idx], overlay_line, col, ov_width, term_width
                    )

        return result

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

        after_start = start_col + overlay_width

        # Extract before/after segments from base line
        segs = extract_segments(
            base_line,
            before_end=start_col,
            after_start=after_start,
            after_len=max(0, total_width - after_start),
            strict_after=True,
        )

        # Slice overlay to its declared width
        ov_text, ov_w = slice_with_width(overlay_line, 0, overlay_width, True)

        before_width = int(segs["before_width"])
        after_width = int(segs["after_width"])

        before_pad = max(0, start_col - before_width)
        overlay_pad = max(0, overlay_width - ov_w)
        actual_before_w = max(start_col, before_width)
        actual_overlay_w = max(overlay_width, ov_w)
        after_target = max(0, total_width - actual_before_w - actual_overlay_w)
        after_pad = max(0, after_target - after_width)

        r = ANSI.SEGMENT_RESET
        result = (
            str(segs["before"])
            + " " * before_pad
            + r
            + ov_text
            + " " * overlay_pad
            + r
            + str(segs["after"])
            + " " * after_pad
        )

        # Safety truncation: never exceed terminal width
        if visible_width(result) > total_width:
            result = slice_by_column(result, 0, total_width, True)

        return result


    def _extract_cursor_position(
        self,
        lines: list[str],
        height: int,
    ) -> tuple[int, int] | None:
        """Scan only the visible viewport for CURSOR_MARKER; strip it; return (row, col)."""
        viewport_top = max(0, len(lines) - height)
        for row_idx in range(len(lines) - 1, viewport_top - 1, -1):
            line = lines[row_idx]
            marker_pos = line.find(ANSI.CURSOR_MARKER)
            if marker_pos == -1:
                continue
            col = visible_width(line[:marker_pos])
            lines[row_idx] = line[:marker_pos] + line[marker_pos + len(ANSI.CURSOR_MARKER):]
            return (row_idx, col)
        return None


    def _position_hardware_cursor(
        self,
        cursor_pos: tuple[int, int] | None,
        total_lines: int,
    ) -> None:
        """Move the terminal hardware cursor for IME candidate window placement."""
        if cursor_pos is None or total_lines <= 0:
            self.terminal.hide_cursor()
            return

        target_row = max(0, min(cursor_pos[0], total_lines - 1))
        target_col = max(0, cursor_pos[1])

        row_delta = target_row - self._hardware_cursor_row
        buf = ""
        if row_delta > 0:
            buf += ANSI.cursor_down(row_delta)
        elif row_delta < 0:
            buf += ANSI.cursor_up(-row_delta)
        buf += ANSI.cursor_column(target_col + 1)

        if buf:
            self.terminal.write(buf)

        self._hardware_cursor_row = target_row
        if self.show_hardware_cursor:
            self.terminal.show_cursor()
        else:
            self.terminal.hide_cursor()
