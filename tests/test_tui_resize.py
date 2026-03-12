"""Tests for TUI resize behaviour.

Verifies that the TUI faithfully replicates the original pi-tui resize
logic: on width/height change it clears the screen + scrollback and
re-renders from scratch via ``fullRender(true)``.
"""

from __future__ import annotations

import re
from typing import Callable

from app.tui.tui import TUI
from app.tui.utils import visible_width


# ---------------------------------------------------------------------------
# Minimal stub terminal
# ---------------------------------------------------------------------------


class StubTerminal:
    """A fake terminal that records writes and allows width/height changes."""

    def __init__(self, columns: int = 80, rows: int = 24) -> None:
        self._columns = columns
        self._rows = rows
        self.writes: list[str] = []
        self._on_input: Callable[[str], None] | None = None
        self._on_resize: Callable[[], None] | None = None

    # -- Terminal protocol --

    def start(self, on_input: Callable[[str], None], on_resize: Callable[[], None]) -> None:
        self._on_input = on_input
        self._on_resize = on_resize

    def stop(self) -> None:
        pass

    def write(self, data: str) -> None:
        self.writes.append(data)

    @property
    def columns(self) -> int:
        return self._columns

    @property
    def rows(self) -> int:
        return self._rows

    def move_by(self, lines: int) -> None:
        pass

    def hide_cursor(self) -> None:
        pass

    def show_cursor(self) -> None:
        pass

    def clear_line(self) -> None:
        pass

    def clear_from_cursor(self) -> None:
        pass

    def clear_screen(self) -> None:
        pass

    def set_title(self, title: str) -> None:
        pass

    # -- Test helpers --

    def resize(self, columns: int, rows: int) -> None:
        """Simulate a terminal resize event."""
        self._columns = columns
        self._rows = rows
        if self._on_resize:
            self._on_resize()

    def last_write(self) -> str:
        return self.writes[-1] if self.writes else ""

    def clear_writes(self) -> None:
        self.writes.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The original pi-tui clear sequence for resize: clear screen, home, clear scrollback
_FULL_CLEAR = "\x1b[2J\x1b[H\x1b[3J"
_BSU = "\x1b[?2026h"  # begin synchronized output
_ESU = "\x1b[?2026l"  # end synchronized output


class _FixedComponent:
    """A component that renders a fixed list of lines."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def render(self, width: int) -> list[str]:
        return list(self.lines)


def _setup_tui(term: StubTerminal, content_lines: list[str]) -> TUI:
    """Create a TUI, do the initial render, and clear write history."""
    tui = TUI(term)
    comp = _FixedComponent(content_lines)
    tui.add_child(comp)
    tui.start()
    # The first render happens via call_soon; force it now.
    tui._do_render()
    term.clear_writes()
    return tui


# ---------------------------------------------------------------------------
# Tests: resize triggers full clear + re-render
# ---------------------------------------------------------------------------


def test_resize_narrower_triggers_full_clear() -> None:
    """Narrowing the terminal must trigger the full clear sequence."""
    term = StubTerminal(columns=100, rows=40)
    content = ["x" * 80 for _ in range(5)]
    tui = _setup_tui(term, content)

    term.resize(50, 40)
    tui._do_render()

    buf = term.last_write()
    assert _FULL_CLEAR in buf, f"Expected full clear sequence in output"


def test_resize_wider_triggers_full_clear() -> None:
    """Widening the terminal must also trigger the full clear sequence."""
    term = StubTerminal(columns=50, rows=40)
    content = ["x" * 40 for _ in range(5)]
    tui = _setup_tui(term, content)

    term.resize(100, 40)
    tui._do_render()

    buf = term.last_write()
    assert _FULL_CLEAR in buf, f"Expected full clear sequence in output"


def test_resize_height_only_triggers_full_clear() -> None:
    """Changing only the height must also trigger a full clear."""
    term = StubTerminal(columns=80, rows=24)
    content = ["y" * 40 for _ in range(5)]
    tui = _setup_tui(term, content)

    term.resize(80, 30)
    tui._do_render()

    buf = term.last_write()
    assert _FULL_CLEAR in buf


def test_resize_resets_max_lines_rendered() -> None:
    """After a resize clear, max_lines_rendered must match the new line count."""
    term = StubTerminal(columns=80, rows=24)
    content = ["z" * 40 for _ in range(7)]
    tui = _setup_tui(term, content)

    assert tui.max_lines_rendered == 7

    term.resize(60, 24)
    tui._do_render()

    assert tui.max_lines_rendered == 7  # same content, same line count


def test_resize_resets_hardware_cursor_row() -> None:
    """After resize, hardware_cursor_row should be set to last line index."""
    term = StubTerminal(columns=80, rows=24)
    content = ["a" * 30 for _ in range(6)]
    tui = _setup_tui(term, content)

    # Move cursor to a middle line to simulate IME positioning
    tui.hardware_cursor_row = 2

    term.resize(60, 24)
    tui._do_render()

    # After full render, cursor should be at last content line
    assert tui.hardware_cursor_row == 5


def test_resize_renders_all_lines() -> None:
    """After resize, all content lines must appear in the output."""
    term = StubTerminal(columns=80, rows=24)
    content = [f"line-{i}" for i in range(4)]
    tui = _setup_tui(term, content)

    term.resize(60, 24)
    tui._do_render()

    buf = term.last_write()
    for i in range(4):
        assert f"line-{i}" in buf, f"line-{i} missing from resize output"


def test_resize_output_wrapped_in_synchronized_output() -> None:
    """The resize output must begin with BSU and end with ESU."""
    term = StubTerminal(columns=80, rows=24)
    content = ["hello" for _ in range(3)]
    tui = _setup_tui(term, content)

    term.resize(60, 24)
    tui._do_render()

    buf = term.last_write()
    assert buf.startswith(_BSU), "Output must begin with BSU"
    assert buf.endswith(_ESU), "Output must end with ESU"


# ---------------------------------------------------------------------------
# Tests: first render (no clear)
# ---------------------------------------------------------------------------


def test_first_render_no_clear() -> None:
    """The very first render must NOT clear the screen."""
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    comp = _FixedComponent(["hello", "world"])
    tui.add_child(comp)
    tui.start()
    tui._do_render()

    buf = term.last_write()
    assert _FULL_CLEAR not in buf, "First render must not clear screen"
    assert "hello" in buf
    assert "world" in buf


# ---------------------------------------------------------------------------
# Tests: differential update (no resize)
# ---------------------------------------------------------------------------


def test_differential_update_no_clear() -> None:
    """A normal re-render with changed content should use differential
    update, not a full clear."""
    term = StubTerminal(columns=80, rows=24)
    comp = _FixedComponent(["line-0", "line-1", "line-2"])
    tui = TUI(term)
    tui.add_child(comp)
    tui.start()
    tui._do_render()
    term.clear_writes()

    # Change one line
    comp.lines[1] = "CHANGED"
    tui.request_render()
    tui._do_render()

    buf = term.last_write()
    assert _FULL_CLEAR not in buf, "Differential update must not clear screen"
    assert "CHANGED" in buf


def test_no_change_no_output() -> None:
    """Re-rendering identical content should produce minimal output."""
    term = StubTerminal(columns=80, rows=24)
    content = ["static" for _ in range(3)]
    tui = _setup_tui(term, content)

    tui.request_render()
    tui._do_render()

    buf = term.last_write()
    # No content should change, only BSU/ESU wrapper
    assert _FULL_CLEAR not in buf
    assert "static" not in buf  # no lines re-written


# ---------------------------------------------------------------------------
# Tests: resize handler behaviour
# ---------------------------------------------------------------------------


def test_resize_handler_does_not_use_force() -> None:
    """The resize handler must call request_render() without force,
    matching the original TS implementation.  Size change is detected
    naturally in _do_render via width_changed/height_changed."""
    term = StubTerminal(columns=80, rows=24)
    content = ["test"]
    tui = _setup_tui(term, content)

    # Verify previous state is intact before resize
    assert tui.previous_width == 80
    assert tui.previous_height == 24
    assert len(tui.previous_lines) == 1

    # Trigger resize — should NOT reset state (no force)
    term._columns = 60
    term._rows = 24
    tui._handle_resize()

    # previous_lines should still be intact (not reset)
    assert tui.previous_lines is not None
    assert len(tui.previous_lines) == 1
    assert tui.previous_width == 80  # not yet updated until render


def test_resize_narrow_then_wide_round_trip() -> None:
    """Narrowing then widening should both produce full clear renders."""
    term = StubTerminal(columns=100, rows=40)
    content = ["m" * 80 for _ in range(5)]
    tui = _setup_tui(term, content)

    # Narrow
    term.resize(40, 40)
    tui._do_render()
    buf1 = term.last_write()
    assert _FULL_CLEAR in buf1
    term.clear_writes()

    # Widen back
    term.resize(100, 40)
    tui._do_render()
    buf2 = term.last_write()
    assert _FULL_CLEAR in buf2


def test_force_render_triggers_full_clear() -> None:
    """request_render(force=True) should set previousWidth=-1 which
    triggers width_changed and thus a full clear on next render."""
    term = StubTerminal(columns=80, rows=24)
    content = ["forced"]
    tui = _setup_tui(term, content)

    tui.request_render(force=True)

    # After force, previous_width should be -1
    assert tui.previous_width == -1
    assert tui.previous_height == -1

    tui._do_render()
    buf = term.last_write()
    assert _FULL_CLEAR in buf
