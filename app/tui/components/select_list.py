"""Keyboard-navigable selection list component."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.tui.keybindings import get_editor_keybindings
from app.tui.utils import truncate_to_width, visible_width

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
class SelectListLayoutOptions:
    min_primary_column_width: int | None = None
    max_primary_column_width: int | None = None


class SelectList:
    def __init__(
        self,
        items: list[SelectItem],
        max_visible: int,
        theme: SelectListTheme,
        layout: SelectListLayoutOptions | None = None,
    ) -> None:
        self._items = list(items)
        self._max_visible = max_visible
        self._theme = theme
        self._layout = layout or SelectListLayoutOptions()
        self._filter: str = ""
        self._filtered: list[SelectItem] = list(items)
        self._selected_index: int = 0
        self._scroll_offset: int = 0

        self.on_select: Callable[[SelectItem], None] | None = None
        self.on_cancel: Callable[[], None] | None = None
        self.on_selection_change: Callable[[SelectItem | None], None] | None = None

    def set_filter(self, filter_text: str) -> None:
        self._filter = filter_text
        lower = filter_text.lower()
        self._filtered = [
            item for item in self._items if item.value.lower().startswith(lower)
        ]
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

    def render(self, width: int) -> list[str]:
        if not self._filtered:
            return [self._theme.no_match("No matches")]

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
                label = truncate_to_width(item.label, primary_col_w - PRIMARY_COLUMN_GAP)
                pad = primary_col_w - visible_width(label)
                label_padded = label + " " * pad
                desc_rendered = self._theme.description(truncate_to_width(desc_text, remaining_for_desc))
                if is_selected:
                    label_padded = self._theme.selected_text(label_padded)
                line = f"{prefix}{label_padded}{desc_rendered}"
            else:
                if desc_text:
                    desc_rendered = self._theme.description(f" — {desc_text}")
                    desc_w = visible_width(desc_rendered)
                    label_avail = max(1, avail - desc_w)
                    label = truncate_to_width(item.label, label_avail)
                else:
                    desc_rendered = ""
                    label = truncate_to_width(item.label, avail)

                if is_selected:
                    label = self._theme.selected_text(label)

                line = f"{prefix}{label}{desc_rendered}"

            line = truncate_to_width(line, width)
            lines.append(line)

        if total > self._max_visible:
            info = f" ({self._selected_index + 1}/{total})"
            lines.append(self._theme.scroll_info(info))

        return lines

    def handle_input(self, data: str) -> None:
        kb = get_editor_keybindings()

        if kb.matches(data, "selectUp"):
            if self._filtered:
                if self._selected_index == 0:
                    self.set_selected_index(len(self._filtered) - 1)
                else:
                    self.set_selected_index(self._selected_index - 1)
        elif kb.matches(data, "selectDown"):
            if self._filtered:
                if self._selected_index == len(self._filtered) - 1:
                    self.set_selected_index(0)
                else:
                    self.set_selected_index(self._selected_index + 1)
        elif kb.matches(data, "selectPageUp"):
            if self._filtered:
                self.set_selected_index(max(0, self._selected_index - self._max_visible))
        elif kb.matches(data, "selectPageDown"):
            if self._filtered:
                self.set_selected_index(min(len(self._filtered) - 1, self._selected_index + self._max_visible))
        elif kb.matches(data, "selectConfirm"):
            item = self.get_selected_item()
            if item and self.on_select:
                self.on_select(item)
        elif kb.matches(data, "selectCancel"):
            if self.on_cancel:
                self.on_cancel()

    def invalidate(self) -> None:
        pass
