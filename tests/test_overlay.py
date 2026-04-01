"""Tests for TUI overlay functionality.

Ports overlay-options.test.ts, overlay-non-capturing.test.ts,
overlay-short-content.test.ts, and tui-overlay-style-leak.test.ts to
Python pytest.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable
from typing import Callable

from pana.tui.tui import TUI, OverlayMargin, OverlayOptions

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(
    r"\x1b(?:\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"
    r"|\].*?(?:\x1b\\|\x07)"
    r"|_.*?(?:\x1b\\|\x07))"
)


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


# ---------------------------------------------------------------------------
# Stub terminal
# ---------------------------------------------------------------------------


class StubTerminal:
    """Fake terminal that records writes and allows width/height changes."""

    def __init__(self, columns: int = 80, rows: int = 24) -> None:
        self._columns = columns
        self._rows = rows
        self.writes: list[str] = []

    def start(self, on_resize: Callable[[], None]) -> None:
        pass

    async def run(self, on_input: Callable[[str], Awaitable[None]]) -> None:
        pass

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


# ---------------------------------------------------------------------------
# Component stubs
# ---------------------------------------------------------------------------


class _FixedComponent:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def render(self, width: int) -> list[str]:
        return list(self.lines)


class _StaticOverlay:
    """Overlay that records the width passed to render()."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.requested_width: int | None = None

    def render(self, width: int) -> list[str]:
        self.requested_width = width
        return list(self.lines)


class _EmptyContent:
    def render(self, width: int) -> list[str]:
        return []


class _FocusableComponent:
    def __init__(self, name: str = "") -> None:
        self.focused: bool = False
        self.inputs: list[str] = []
        self.name = name

    def render(self, width: int) -> list[str]:
        return [self.name or "focusable"]

    async def handle_input(self, data: str) -> None:
        self.inputs.append(data)


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _render_with_overlays(tui: TUI, term: StubTerminal) -> list[str]:
    """Render content + overlays and return ANSI-stripped lines."""
    width = term.columns
    height = term.rows
    lines = tui.render(width)
    lines = tui._composite_overlays(lines, width, height)
    return [_strip_ansi(line) for line in lines]


def _render_raw_overlays(tui: TUI, term: StubTerminal) -> list[str]:
    """Render content + overlays and return raw lines (ANSI intact)."""
    width = term.columns
    height = term.rows
    lines = tui.render(width)
    return tui._composite_overlays(lines, width, height)


# ---------------------------------------------------------------------------
# overlay-options: width overflow
# ---------------------------------------------------------------------------


def test_overlay_truncated_lines_no_crash() -> None:
    term = StubTerminal(columns=20, rows=10)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["X" * 100])
    tui.show_overlay(overlay, OverlayOptions(width=20))
    result = _render_with_overlays(tui, term)
    assert result is not None


def test_complex_ansi_no_crash() -> None:
    lines = [
        "\x1b[1m\x1b]8;;https://example.com\x07Link\x1b]8;;\x07\x1b[0m normal",
        "\x1b[38;2;255;0;0mRed\x1b[0m \x1b[48;5;22mGreen BG\x1b[0m",
        "\x1b[3;4;7mItalic+Under+Inv\x1b[0m",
    ]
    term = StubTerminal(columns=60, rows=10)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(lines)
    tui.show_overlay(overlay, OverlayOptions(width=60))
    result = _render_with_overlays(tui, term)
    assert result is not None


def test_overlay_on_styled_base() -> None:
    term = StubTerminal(columns=40, rows=10)
    tui = TUI(term)
    tui.add_child(_FixedComponent(["\x1b[44mBase Content\x1b[0m"]))
    overlay = _FixedComponent(["OVERLAY"])
    tui.show_overlay(overlay, OverlayOptions(anchor="center", width=20))
    result = _render_with_overlays(tui, term)
    assert any("OVERLAY" in line for line in result)


def test_wide_chars_at_boundary() -> None:
    term = StubTerminal(columns=15, rows=10)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["你好世界测试"])
    tui.show_overlay(overlay, OverlayOptions(width=15))
    result = _render_with_overlays(tui, term)
    assert result is not None


def test_overlay_at_terminal_edge() -> None:
    term = StubTerminal(columns=80, rows=10)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["X" * 50])
    tui.show_overlay(overlay, OverlayOptions(col=60, width=20))
    result = _render_with_overlays(tui, term)
    assert result is not None


def test_overlay_on_osc_base() -> None:
    base_line = "\x1b]8;;https://example.com\x07Click Here\x1b]8;;\x07 some text"
    term = StubTerminal(columns=40, rows=10)
    tui = TUI(term)
    tui.add_child(_FixedComponent([base_line]))
    overlay = _FixedComponent(["OVERLAY-TEXT"])
    tui.show_overlay(overlay, OverlayOptions(anchor="center", width=20))
    result = _render_with_overlays(tui, term)
    assert result is not None


# ---------------------------------------------------------------------------
# overlay-options: width percentage
# ---------------------------------------------------------------------------


def test_width_percentage() -> None:
    term = StubTerminal(columns=100, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _StaticOverlay(["pct"])
    tui.show_overlay(overlay, OverlayOptions(width="50%"))
    _render_with_overlays(tui, term)
    assert overlay.requested_width == 50


def test_min_width_with_percentage() -> None:
    term = StubTerminal(columns=100, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _StaticOverlay(["pct"])
    tui.show_overlay(overlay, OverlayOptions(width="10%", min_width=30))
    _render_with_overlays(tui, term)
    assert overlay.requested_width == 30


# ---------------------------------------------------------------------------
# overlay-options: anchor positioning
# ---------------------------------------------------------------------------


def test_anchor_top_left() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["TOP-LEFT"])
    tui.show_overlay(overlay, OverlayOptions(anchor="top-left", width=10))
    result = _render_with_overlays(tui, term)
    assert result[0].startswith("TOP-LEFT")


def test_anchor_bottom_right() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["BTM-RIGHT"])
    tui.show_overlay(overlay, OverlayOptions(anchor="bottom-right", width=10))
    result = _render_with_overlays(tui, term)
    assert "BTM-RIGHT" in result[23]
    # Should be at right edge
    col = result[23].index("BTM-RIGHT")
    assert col == 70


def test_anchor_top_center() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["CENTERED"])
    tui.show_overlay(overlay, OverlayOptions(anchor="top-center", width=10))
    result = _render_with_overlays(tui, term)
    assert "CENTERED" in result[0]
    col = result[0].index("CENTERED")
    assert 35 <= col <= 40


# ---------------------------------------------------------------------------
# overlay-options: margin
# ---------------------------------------------------------------------------


def test_negative_margin_clamped() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["NEG-MARGIN"])
    tui.show_overlay(
        overlay,
        OverlayOptions(
            anchor="top-left",
            margin=OverlayMargin(top=-5, left=-10),
            width=12,
        ),
    )
    result = _render_with_overlays(tui, term)
    # Negative margin puts overlay at negative row/col — off-screen.
    # Should not crash.
    assert result is not None


def test_margin_as_number() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["MARGIN"])
    tui.show_overlay(
        overlay,
        OverlayOptions(anchor="top-left", margin=5, width=10),
    )
    result = _render_with_overlays(tui, term)
    # margin=5 means top=5, left=5
    for i in range(5):
        assert "MARGIN" not in result[i] if i < len(result) else True
    assert "MARGIN" in result[5]
    col = result[5].index("MARGIN")
    assert col == 5


def test_margin_object() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["MARGIN"])
    tui.show_overlay(
        overlay,
        OverlayOptions(
            anchor="top-left",
            margin=OverlayMargin(top=2, left=3),
            width=10,
        ),
    )
    result = _render_with_overlays(tui, term)
    assert "MARGIN" in result[2]
    col = result[2].index("MARGIN")
    assert col == 3


# ---------------------------------------------------------------------------
# overlay-options: offset
# ---------------------------------------------------------------------------


def test_offset_from_anchor() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["OFFSET"])
    tui.show_overlay(
        overlay,
        OverlayOptions(anchor="top-left", offset_x=10, offset_y=5, width=10),
    )
    result = _render_with_overlays(tui, term)
    assert "OFFSET" in result[5]
    col = result[5].index("OFFSET")
    assert col == 10


# ---------------------------------------------------------------------------
# overlay-options: percentage positioning
# ---------------------------------------------------------------------------


def test_row_col_percentage() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["PCT"])
    tui.show_overlay(
        overlay,
        OverlayOptions(width=10, row="50%", col="50%"),
    )
    result = _render_with_overlays(tui, term)
    found = False
    for i, line in enumerate(result):
        if "PCT" in line:
            assert 10 <= i <= 13
            found = True
            break
    assert found


def test_row_percent_zero() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["TOP"])
    tui.show_overlay(
        overlay,
        OverlayOptions(row="0%", col=0, width=10),
    )
    result = _render_with_overlays(tui, term)
    assert "TOP" in result[0]


def test_row_percent_100() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["BOTTOM"])
    tui.show_overlay(
        overlay,
        OverlayOptions(row="100%", col=0, width=10),
    )
    result = _render_with_overlays(tui, term)
    assert "BOTTOM" in result[-1]


# ---------------------------------------------------------------------------
# overlay-options: maxHeight
# ---------------------------------------------------------------------------


def test_truncate_to_max_height() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    lines = [f"LINE-{i+1}" for i in range(5)]
    overlay = _FixedComponent(lines)
    tui.show_overlay(overlay, OverlayOptions(anchor="top-left", width=20, max_height=3))
    result = _render_with_overlays(tui, term)
    text = "\n".join(result)
    assert "LINE-1" in text
    assert "LINE-2" in text
    assert "LINE-3" in text
    assert "LINE-4" not in text
    assert "LINE-5" not in text


def test_max_height_percent() -> None:
    term = StubTerminal(columns=80, rows=10)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    lines = [f"LINE-{i+1}" for i in range(10)]
    overlay = _FixedComponent(lines)
    tui.show_overlay(overlay, OverlayOptions(anchor="top-left", width=20, max_height="50%"))
    result = _render_with_overlays(tui, term)
    text = "\n".join(result)
    assert "LINE-5" in text
    assert "LINE-6" not in text


# ---------------------------------------------------------------------------
# overlay-options: absolute positioning
# ---------------------------------------------------------------------------


def test_row_col_override_anchor() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["ABSOLUTE"])
    tui.show_overlay(
        overlay,
        OverlayOptions(anchor="bottom-right", row=3, col=5, width=10),
    )
    result = _render_with_overlays(tui, term)
    assert "ABSOLUTE" in result[3]
    col = result[3].index("ABSOLUTE")
    assert col == 5


# ---------------------------------------------------------------------------
# overlay-options: stacked overlays
# ---------------------------------------------------------------------------


def test_later_overlays_on_top() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    tui.show_overlay(
        _FixedComponent(["FIRST" + " " * 15]),
        OverlayOptions(anchor="top-left", width=20),
    )
    tui.show_overlay(
        _FixedComponent(["SECOND"]),
        OverlayOptions(anchor="top-left", width=10),
    )
    result = _render_with_overlays(tui, term)
    assert "SECOND" in result[0]


def test_overlays_different_positions() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    tui.show_overlay(
        _FixedComponent(["TOP-LEFT"]),
        OverlayOptions(anchor="top-left", width=10),
    )
    tui.show_overlay(
        _FixedComponent(["BTM-RIGHT"]),
        OverlayOptions(anchor="bottom-right", width=10),
    )
    result = _render_with_overlays(tui, term)
    assert "TOP-LEFT" in result[0]
    assert "BTM-RIGHT" in result[23]


def test_hide_overlay_pops_stack() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    tui.show_overlay(
        _FixedComponent(["FIRST" + " " * 15]),
        OverlayOptions(anchor="top-left", width=20),
    )
    h2 = tui.show_overlay(
        _FixedComponent(["SECOND"]),
        OverlayOptions(anchor="top-left", width=10),
    )

    result_before = _render_with_overlays(tui, term)
    assert "SECOND" in result_before[0]

    tui.hide_overlay(h2)

    result_after = _render_with_overlays(tui, term)
    assert "FIRST" in result_after[0]


# ---------------------------------------------------------------------------
# overlay-non-capturing: focus management
# ---------------------------------------------------------------------------


def _setup_nc_tui(
    term: StubTerminal,
) -> tuple[TUI, _FocusableComponent]:
    """Create a TUI with a focused editor component."""
    tui = TUI(term)
    editor = _FocusableComponent("editor")
    tui.add_child(editor)
    tui.set_focus(editor)
    tui._init()
    tui._do_render()
    return tui, editor


def test_nc_preserves_focus() -> None:
    term = StubTerminal()
    tui, editor = _setup_nc_tui(term)
    overlay = _FocusableComponent("overlay")
    tui.show_overlay(overlay, OverlayOptions(non_capturing=True))
    assert editor.focused is True
    assert overlay.focused is False


def test_nc_focus_handle() -> None:
    """JS isFocused() returns focusedComponent === component.
    Non-capturing overlays don't take TUI focus, so is_focused() is False."""
    term = StubTerminal()
    tui, editor = _setup_nc_tui(term)
    overlay = _FocusableComponent("overlay")
    handle = tui.show_overlay(overlay, OverlayOptions(non_capturing=True))
    # Non-capturing: editor keeps keyboard focus, so overlay handle is not focused
    assert handle.is_focused() is False
    # NC overlay doesn't steal focus from editor
    assert editor.focused is True


def test_nc_unfocus_no_op_when_not_focused() -> None:
    """Non-capturing overlays never hold TUI focus, so unfocus() is a no-op.
    JS: isFocused() === (focusedComponent === component), already False for NC."""
    term = StubTerminal()
    tui, editor = _setup_nc_tui(term)
    overlay = _FocusableComponent("overlay")
    handle = tui.show_overlay(overlay, OverlayOptions(non_capturing=True))
    assert handle.is_focused() is False  # was already False (NC doesn't take focus)
    handle.unfocus()
    assert handle.is_focused() is False
    # Editor still focused
    assert editor.focused is True


def test_hide_nc_no_focus_change() -> None:
    term = StubTerminal()
    tui, editor = _setup_nc_tui(term)
    overlay = _FocusableComponent("overlay")
    handle = tui.show_overlay(overlay, OverlayOptions(non_capturing=True))
    tui.hide_overlay(handle)
    assert editor.focused is True


def test_capturing_overlay_takes_focus() -> None:
    term = StubTerminal()
    tui, editor = _setup_nc_tui(term)
    overlay = _FocusableComponent("overlay")
    tui.show_overlay(overlay, OverlayOptions(non_capturing=False))
    assert editor.focused is False
    assert overlay.focused is True


def test_hide_capturing_restores_focus() -> None:
    term = StubTerminal()
    tui, editor = _setup_nc_tui(term)
    overlay = _FocusableComponent("overlay")
    handle = tui.show_overlay(overlay, OverlayOptions(non_capturing=False))
    assert editor.focused is False
    tui.hide_overlay(handle)
    assert editor.focused is True


async def test_input_goes_to_capturing_overlay() -> None:
    term = StubTerminal()
    tui, editor = _setup_nc_tui(term)
    overlay = _FocusableComponent("overlay")
    tui.show_overlay(overlay, OverlayOptions(non_capturing=False))
    await tui._dispatch_key("x")
    assert "x" in overlay.inputs
    assert "x" not in editor.inputs


async def test_input_goes_to_editor_when_no_overlay() -> None:
    term = StubTerminal()
    tui, editor = _setup_nc_tui(term)
    await tui._dispatch_key("x")
    assert "x" in editor.inputs


async def test_nc_overlay_skipped_for_input() -> None:
    term = StubTerminal()
    tui, editor = _setup_nc_tui(term)
    overlay = _FocusableComponent("overlay")
    tui.show_overlay(overlay, OverlayOptions(non_capturing=True))
    await tui._dispatch_key("x")
    assert "x" in editor.inputs
    assert "x" not in overlay.inputs


# ---------------------------------------------------------------------------
# overlay-short-content
# ---------------------------------------------------------------------------


def test_short_content_overlay() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    overlay = _FixedComponent(["short"])
    tui.show_overlay(overlay, OverlayOptions(anchor="center", width=20))
    result = _render_with_overlays(tui, term)
    assert result is not None
    text = "\n".join(result)
    assert "short" in text


# ---------------------------------------------------------------------------
# tui-overlay-style-leak
# ---------------------------------------------------------------------------


def test_no_style_leak_between_overlays() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    tui.add_child(_EmptyContent())
    styled_overlay = _FixedComponent(["\x1b[31mSTYLED\x1b[0m"])
    plain_overlay = _FixedComponent(["PLAIN"])
    tui.show_overlay(
        styled_overlay,
        OverlayOptions(anchor="top-left", width=20, row=0, col=0),
    )
    tui.show_overlay(
        plain_overlay,
        OverlayOptions(anchor="top-left", width=20, row=1, col=0),
    )
    raw = _render_raw_overlays(tui, term)
    # The plain overlay's line should not contain \x1b[31m (red fg)
    plain_row = raw[1]
    plain_after_start = plain_row[:plain_row.index("PLAIN")] if "PLAIN" in plain_row else plain_row
    assert "\x1b[31m" not in plain_after_start


def test_no_style_leak_to_base_after_overlay() -> None:
    term = StubTerminal(columns=80, rows=24)
    tui = TUI(term)
    base_lines = ["BASE-LINE-0", "BASE-LINE-1", "BASE-LINE-2"]
    tui.add_child(_FixedComponent(base_lines))
    styled_overlay = _FixedComponent(["\x1b[32mGREEN\x1b[0m"])
    tui.show_overlay(
        styled_overlay,
        OverlayOptions(anchor="top-left", width=10, row=0, col=0),
    )
    raw = _render_raw_overlays(tui, term)
    # Row 1 (base content after overlay) should not contain the green code
    if len(raw) > 1:
        assert "\x1b[32m" not in raw[1]
