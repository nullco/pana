"""Tests for the SelectList component."""

from __future__ import annotations

from pana.tui.components.select_list import (
    SelectItem,
    SelectList,
    SelectListLayoutOptions,
    SelectListTheme,
)
from pana.tui.utils import visible_width

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _identity(s: str) -> str:
    return s


_THEME = SelectListTheme(
    selected_prefix=_identity,
    selected_text=_identity,
    description=_identity,
    scroll_info=_identity,
    no_match=_identity,
)

# Arrow key escape sequences
_UP = "\x1b[A"
_DOWN = "\x1b[B"
_PAGE_UP = "\x1b[5~"
_PAGE_DOWN = "\x1b[6~"


def _make_list(
    items: list[SelectItem],
    max_visible: int = 10,
    layout: SelectListLayoutOptions | None = None,
) -> SelectList:
    return SelectList(items=items, max_visible=max_visible, theme=_THEME, layout=layout)


# ---------------------------------------------------------------------------
# Tests: description normalisation
# ---------------------------------------------------------------------------


def test_normalizes_multiline_descriptions_to_single_line() -> None:
    """Multi-line descriptions (\\n, \\r\\n) must be collapsed to spaces."""
    items = [SelectItem(value="a", label="alpha", description="line1\nline2\r\nline3")]
    sl = _make_list(items)
    lines = sl.render(80)
    for line in lines:
        assert "\n" not in line
        assert "\r" not in line
    assert "line1 line2 line3" in lines[0]


# ---------------------------------------------------------------------------
# Tests: description alignment with truncated primary text
# ---------------------------------------------------------------------------


def test_descriptions_aligned_when_primary_text_truncated() -> None:
    """Descriptions must start at the same column even when labels differ in length."""
    items = [
        SelectItem(value="short", label="AB", description="desc-short"),
        SelectItem(value="long", label="A" * 50, description="desc-long"),
    ]
    sl = _make_list(items)
    lines = sl.render(80)

    # Both descriptions should appear; find column where "desc-" starts
    positions = [line.find("desc-") for line in lines if "desc-" in line]
    assert len(positions) == 2
    assert positions[0] == positions[1], "Descriptions must be aligned"


# ---------------------------------------------------------------------------
# Tests: layout column width constraints
# ---------------------------------------------------------------------------


def test_uses_configured_minimum_primary_column_width() -> None:
    """min_primary_column_width must prevent the primary column from shrinking."""
    items = [SelectItem(value="x", label="AB", description="info")]
    layout = SelectListLayoutOptions(min_primary_column_width=30)
    sl = _make_list(items, layout=layout)
    lines = sl.render(80)
    # The description should start at or after column 30 + prefix width
    desc_pos = lines[0].find("info")
    prefix_w = visible_width("→ ")
    assert desc_pos >= prefix_w + 30


def test_uses_configured_maximum_primary_column_width() -> None:
    """max_primary_column_width must prevent the primary column from growing."""
    items = [SelectItem(value="x", label="A" * 60, description="info")]
    layout = SelectListLayoutOptions(max_primary_column_width=20)
    sl = _make_list(items, layout=layout)
    lines = sl.render(80)
    desc_pos = lines[0].find("info")
    prefix_w = visible_width("→ ")
    # Description should start no later than prefix + max_col
    assert desc_pos <= prefix_w + 20


# ---------------------------------------------------------------------------
# Tests: wrap-around navigation
# ---------------------------------------------------------------------------


def test_wraps_up_from_first_item_to_last() -> None:
    """Pressing up on the first item must wrap to the last item."""
    items = [SelectItem(value=str(i), label=f"item-{i}") for i in range(5)]
    sl = _make_list(items)
    assert sl._selected_index == 0
    sl.handle_input(_UP)
    assert sl._selected_index == 4


def test_wraps_down_from_last_item_to_first() -> None:
    """Pressing down on the last item must wrap to the first item."""
    items = [SelectItem(value=str(i), label=f"item-{i}") for i in range(5)]
    sl = _make_list(items)
    sl.set_selected_index(4)
    sl.handle_input(_DOWN)
    assert sl._selected_index == 0


# ---------------------------------------------------------------------------
# Tests: page up / page down
# ---------------------------------------------------------------------------


def test_page_up_moves_by_max_visible_items() -> None:
    """Page up must move the selection up by max_visible items."""
    items = [SelectItem(value=str(i), label=f"item-{i}") for i in range(20)]
    sl = _make_list(items, max_visible=5)
    sl.set_selected_index(12)
    sl.handle_input(_PAGE_UP)
    assert sl._selected_index == 7


def test_page_down_moves_by_max_visible_items() -> None:
    """Page down must move the selection down by max_visible items."""
    items = [SelectItem(value=str(i), label=f"item-{i}") for i in range(20)]
    sl = _make_list(items, max_visible=5)
    sl.set_selected_index(3)
    sl.handle_input(_PAGE_DOWN)
    assert sl._selected_index == 8


# ---------------------------------------------------------------------------
# Tests: centered viewport
# ---------------------------------------------------------------------------


def test_centered_viewport_keeps_selected_item_visible() -> None:
    """The selected item must always be visible in the rendered output."""
    items = [SelectItem(value=str(i), label=f"item-{i}") for i in range(20)]
    sl = _make_list(items, max_visible=5)

    for idx in [0, 4, 10, 15, 19]:
        sl.set_selected_index(idx)
        lines = sl.render(80)
        # The selected item label must appear in the rendered lines
        label = f"item-{idx}"
        rendered_labels = " ".join(lines)
        assert label in rendered_labels, f"item-{idx} not visible at index {idx}"


# ---------------------------------------------------------------------------
# Tests: two-column layout activation
# ---------------------------------------------------------------------------


def test_two_column_layout_activates_when_width_over_40_and_description_exists() -> None:
    """When width > 40 and items have descriptions, two-column layout must be used."""
    items = [
        SelectItem(value="a", label="Alpha", description="First letter"),
        SelectItem(value="b", label="Beta", description="Second letter"),
    ]
    sl = _make_list(items)
    lines = sl.render(60)
    # In two-column mode, descriptions are aligned (not prefixed with " — ")
    for line in lines:
        if "letter" in line:
            assert " — " not in line, "Two-column mode should not use dash separator"


def test_falls_back_to_single_column_when_width_40_or_less() -> None:
    """When width <= 40, the list must fall back to single-column layout."""
    items = [
        SelectItem(value="a", label="Alpha", description="First letter"),
    ]
    sl = _make_list(items)
    lines = sl.render(40)
    # Single-column mode uses " — " separator
    assert " — " in lines[0], "Single-column mode should use dash separator"


# ---------------------------------------------------------------------------
# Tests: scroll indicator format
# ---------------------------------------------------------------------------


def test_scroll_indicator_shows_index_total_format() -> None:
    """When items exceed max_visible, scroll indicator must show (index/total)."""
    items = [SelectItem(value=str(i), label=f"item-{i}") for i in range(10)]
    sl = _make_list(items, max_visible=3)
    lines = sl.render(80)
    # Last line should be the scroll indicator
    assert lines[-1].strip().startswith("(")
    assert "1/10" in lines[-1]


# ---------------------------------------------------------------------------
# Tests: searchable mode
# ---------------------------------------------------------------------------

_BACKSPACE = "\x7f"


def test_searchable_renders_search_input_line() -> None:
    """Searchable list must render a search input line at the top."""
    items = [SelectItem(value="a", label="alpha"), SelectItem(value="b", label="beta")]
    sl = SelectList(items, 10, _THEME, searchable=True)
    lines = sl.render(60)
    assert lines[0].startswith("> ")


def test_searchable_filters_by_typing() -> None:
    """Typing characters must filter the list using fuzzy matching."""
    items = [
        SelectItem(value="alpha", label="alpha"),
        SelectItem(value="beta", label="beta"),
        SelectItem(value="gamma", label="gamma"),
    ]
    sl = SelectList(items, 10, _THEME, searchable=True)
    sl.handle_input("b")
    assert len(sl._filtered) == 1
    assert sl._filtered[0].value == "beta"


def test_searchable_backspace_widens_filter() -> None:
    """Backspace must remove the last character and widen the filter."""
    items = [
        SelectItem(value="alpha", label="alpha"),
        SelectItem(value="beta", label="beta"),
    ]
    sl = SelectList(items, 10, _THEME, searchable=True)
    sl.handle_input("b")
    assert len(sl._filtered) == 1
    sl.handle_input(_BACKSPACE)
    assert len(sl._filtered) == 2


def test_searchable_shows_no_matches() -> None:
    """When no items match, 'No matches' must be shown."""
    items = [SelectItem(value="alpha", label="alpha")]
    sl = SelectList(items, 10, _THEME, searchable=True)
    sl.handle_input("z")
    sl.handle_input("z")
    sl.handle_input("z")
    lines = sl.render(60)
    assert any("No matches" in l for l in lines)


def test_non_searchable_ignores_text_input() -> None:
    """Non-searchable list must not react to character input."""
    items = [
        SelectItem(value="alpha", label="alpha"),
        SelectItem(value="beta", label="beta"),
    ]
    sl = _make_list(items)
    sl.handle_input("b")
    # Should still show all items (no filtering)
    assert len(sl._filtered) == 2
