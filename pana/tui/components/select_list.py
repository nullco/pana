"""Keyboard-navigable selection list component with optional search filtering."""
from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Callable

from pana.tui.fuzzy import fuzzy_filter
from pana.tui.keybindings import get_editor_keybindings
from pana.tui.keys import decode_kitty_printable
from pana.tui.utils import truncate_to_width, visible_width

DEFAULT_PRIMARY_COLUMN_WIDTH = 32
PRIMARY_COLUMN_GAP = 2
MIN_DESCRIPTION_WIDTH = 10


@dataclass
class SelectItem:
    value: str
    label: str
    description: str | None = None


@dataclass
class SelectListTheme:
    selected_prefix: Callable[[str], str]
    selected_text: Callable[[str], str]
    description: Callable[[str], str]
    scroll_info: Callable[[str], str]
    no_match: Callable[[str], str]


@dataclass
class SelectListTruncatePrimaryContext:
    """Context passed to custom truncate_primary callbacks."""
    text: str
    max_width: int
    column_width: int
    item: SelectItem
    is_selected: bool


@dataclass
class SelectListLayoutOptions:
    min_primary_column_width: int | None = None
    max_primary_column_width: int | None = None
    truncate_primary: Callable[[SelectListTruncatePrimaryContext], str] | None = None


class SelectList:
    def __init__(
        self,
        items: list[SelectItem],
        max_visible: int,
        theme: SelectListTheme,
        layout: SelectListLayoutOptions | None = None,
        *,
        searchable: bool = False,
    ) -> None:
        self._items = list(items)
        self._max_visible = max_visible
        self._theme = theme
        self._layout = layout or SelectListLayoutOptions()
        self._filter: str = ""
        self._filtered: list[SelectItem] = list(items)
        self._selected_index: int = 0
        self._scroll_offset: int = 0
        self._searchable = searchable

        self.focused: bool = False

        self.on_select: Callable[[SelectItem], Awaitable[None]] | None = None
        self.on_cancel: Callable[[], Awaitable[None]] | None = None
        self.on_selection_change: Callable[[SelectItem | None], None] | None = None

    def set_filter(self, filter_text: str) -> None:
        self._filter = filter_text
        if filter_text.strip():
            self._filtered = fuzzy_filter(
                self._items, filter_text, lambda item: item.label,
            )
        else:
            self._filtered = list(self._items)
        self._selected_index = 0
        self._scroll_offset = 0
        if self.on_selection_change:
            self.on_selection_change(self.get_selected_item())

    def set_selected_index(self, index: int) -> None:
        if not self._filtered:
            return
        self._selected_index = max(0, min(index, len(self._filtered) - 1))
        self._ensure_visible()
        if self.on_selection_change:
            self.on_selection_change(self.get_selected_item())

    def get_selected_item(self) -> SelectItem | None:
        if not self._filtered or self._selected_index >= len(self._filtered):
            return None
        return self._filtered[self._selected_index]

    def _ensure_visible(self) -> None:
        if self._selected_index < self._scroll_offset:
            self._scroll_offset = self._selected_index
        elif self._selected_index >= self._scroll_offset + self._max_visible:
            self._scroll_offset = self._selected_index - self._max_visible + 1

    def _get_primary_column_width(self) -> int:
        if not self._filtered:
            return DEFAULT_PRIMARY_COLUMN_WIDTH
        widest = max(visible_width(item.label) for item in self._filtered)
        col_width = widest + PRIMARY_COLUMN_GAP
        min_w = self._layout.min_primary_column_width
        max_w = self._layout.max_primary_column_width
        if min_w is not None:
            col_width = max(col_width, min_w)
        if max_w is not None:
            col_width = min(col_width, max_w)
        return col_width

    def _normalize_description(self, desc: str) -> str:
        return desc.replace("\r\n", " ").replace("\n", " ")

    def _truncate_primary(
        self, item: SelectItem, is_selected: bool, max_width: int, column_width: int
    ) -> str:
        """Truncate the primary column text, using custom callback if provided."""
        display_value = item.label
        if self._layout.truncate_primary:
            truncated = self._layout.truncate_primary(
                SelectListTruncatePrimaryContext(
                    text=display_value,
                    max_width=max_width,
                    column_width=column_width,
                    item=item,
                    is_selected=is_selected,
                )
            )
        else:
            truncated = truncate_to_width(display_value, max_width, "")
        # Always enforce the max_width limit
        return truncate_to_width(truncated, max_width, "")

    def render(self, width: int) -> list[str]:
        result: list[str] = []

        # Search input line
        if self._searchable:
            prompt = "> "
            query_display = self._filter
            avail = max(1, width - len(prompt))
            query_display = truncate_to_width(query_display, avail)
            cursor = "\x1b[7m \x1b[0m"
            line = f"{prompt}{query_display}{cursor}"
            pad = max(0, width - visible_width(prompt) - visible_width(query_display) - 1)
            result.append(line + " " * pad)

        if not self._filtered:
            result.append(self._theme.no_match("  No matches"))
            return result

        total = len(self._filtered)

        # Centered viewport scrolling
        start_index = max(0, min(self._selected_index - self._max_visible // 2, total - self._max_visible))
        end_index = min(start_index + self._max_visible, total)
        visible_items = self._filtered[start_index:end_index]

        primary_col_w = self._get_primary_column_width()

        lines: list[str] = []
        for i, item in enumerate(visible_items):
            abs_index = start_index + i
            is_selected = abs_index == self._selected_index

            if is_selected:
                prefix = self._theme.selected_prefix("→ ")
            else:
                prefix = "  "

            prefix_w = visible_width(prefix)
            avail = width - prefix_w

            desc_text = self._normalize_description(item.description) if item.description else None
            remaining_for_desc = avail - primary_col_w

            if desc_text and width > 40 and remaining_for_desc >= MIN_DESCRIPTION_WIDTH:
                effective_col_w = max(1, min(primary_col_w, avail - 4))
                max_primary_w = max(1, effective_col_w - PRIMARY_COLUMN_GAP)
                label = self._truncate_primary(item, is_selected, max_primary_w, effective_col_w)
                label_w = visible_width(label)
                pad = " " * max(1, effective_col_w - label_w)
                desc_start = prefix_w + label_w + len(pad)
                desc_avail = width - desc_start - 2
                if desc_avail > MIN_DESCRIPTION_WIDTH:
                    desc_truncated = truncate_to_width(desc_text, desc_avail, "")
                    if is_selected:
                        line = self._theme.selected_text(f"{prefix}{label}{pad}{desc_truncated}")
                    else:
                        line = f"{prefix}{label}{self._theme.description(pad + desc_truncated)}"
                else:
                    # Fall through to single-column
                    max_w = avail - 2
                    label = self._truncate_primary(item, is_selected, max_w, max_w)
                    if is_selected:
                        line = self._theme.selected_text(f"{prefix}{label}")
                    else:
                        line = f"{prefix}{label}"
            else:
                max_w = avail - 2
                label = self._truncate_primary(item, is_selected, max_w, max_w)
                if desc_text:
                    desc_rendered = self._theme.description(f" — {desc_text}")
                    desc_w = visible_width(desc_rendered)
                    label_avail = max(1, avail - desc_w)
                    label = self._truncate_primary(item, is_selected, label_avail, label_avail)
                else:
                    desc_rendered = ""

                if is_selected:
                    label = self._theme.selected_text(label)

                line = f"{prefix}{label}{desc_rendered}"

            line = truncate_to_width(line, width)
            lines.append(line)

        if total > self._max_visible:
            info = f"  ({self._selected_index + 1}/{total})"
            lines.append(self._theme.scroll_info(info))

        result.extend(lines)
        return result

    async def handle_input(self, data: str) -> None:
        kb = get_editor_keybindings()

        if kb.matches(data, "tui.select.up"):
            if self._filtered:
                if self._selected_index == 0:
                    self.set_selected_index(len(self._filtered) - 1)
                else:
                    self.set_selected_index(self._selected_index - 1)
            return
        if kb.matches(data, "tui.select.down"):
            if self._filtered:
                if self._selected_index == len(self._filtered) - 1:
                    self.set_selected_index(0)
                else:
                    self.set_selected_index(self._selected_index + 1)
            return
        if kb.matches(data, "tui.select.pageUp"):
            if self._filtered:
                self.set_selected_index(max(0, self._selected_index - self._max_visible))
            return
        if kb.matches(data, "tui.select.pageDown"):
            if self._filtered:
                self.set_selected_index(min(len(self._filtered) - 1, self._selected_index + self._max_visible))
            return
        if kb.matches(data, "tui.select.confirm") or kb.matches(data, "tui.input.tab"):
            item = self.get_selected_item()
            if item and self.on_select:
                await self.on_select(item)
            return
        if kb.matches(data, "tui.select.cancel"):
            if self.on_cancel:
                await self.on_cancel()
            return

        # Text input for searchable lists
        if self._searchable:
            if kb.matches(data, "tui.editor.deleteCharBackward"):
                if self._filter:
                    self.set_filter(self._filter[:-1])
                return
            if kb.matches(data, "tui.editor.deleteToLineStart"):
                self.set_filter("")
                return

            ch = decode_kitty_printable(data)
            if ch is not None:
                self.set_filter(self._filter + ch)
                return
            if data and len(data) == 1 and ord(data[0]) >= 32:
                self.set_filter(self._filter + data)
                return

    def invalidate(self) -> None:
        pass
