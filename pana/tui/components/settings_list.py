"""Settings panel with value cycling and submenus."""
from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Callable

from pana.tui.components.input import Input
from pana.tui.fuzzy import fuzzy_filter
from pana.tui.keybindings import get_editor_keybindings
from pana.tui.utils import truncate_to_width, visible_width, wrap_text_with_ansi


@dataclass
class SettingItem:
    id: str
    label: str
    current_value: str
    description: str | None = None
    values: list[str] | None = None
    submenu: Callable[[str, Callable[[str | None], Awaitable[None]]], Any] | None = None


@dataclass
class SettingsListTheme:
    label: Callable[[str, bool], str]
    value: Callable[[str, bool], str]
    description: Callable[[str], str]
    cursor: str
    hint: Callable[[str], str]


class SettingsList:
    def __init__(
        self,
        items: list[SettingItem],
        max_visible: int,
        theme: SettingsListTheme,
        on_change: Callable[[str, str], Awaitable[None]],
        on_cancel: Callable[[], Awaitable[None]],
        *,
        enable_search: bool = False,
    ) -> None:
        self._items = items
        self._filtered_items = list(items)
        self._theme = theme
        self._selected_index = 0
        self._max_visible = max_visible
        self._on_change = on_change
        self._on_cancel = on_cancel
        self._search_enabled = enable_search
        self._search_input: Input | None = Input() if enable_search else None
        self._submenu_component: Any = None
        self._submenu_item_index: int | None = None

    def update_value(self, id: str, new_value: str) -> None:
        for item in self._items:
            if item.id == id:
                item.current_value = new_value
                break

    def invalidate(self) -> None:
        if self._submenu_component and hasattr(self._submenu_component, "invalidate"):
            self._submenu_component.invalidate()

    def render(self, width: int) -> list[str]:
        if self._submenu_component:
            return self._submenu_component.render(width)
        return self._render_main_list(width)

    def _render_main_list(self, width: int) -> list[str]:
        lines: list[str] = []

        if self._search_enabled and self._search_input:
            lines.extend(self._search_input.render(width))
            lines.append("")

        if not self._items:
            lines.append(self._theme.hint("  No settings available"))
            if self._search_enabled:
                self._add_hint_line(lines, width)
            return lines

        display = self._filtered_items if self._search_enabled else self._items
        if not display:
            lines.append(truncate_to_width(self._theme.hint("  No matching settings"), width))
            self._add_hint_line(lines, width)
            return lines

        start = max(0, min(
            self._selected_index - self._max_visible // 2,
            len(display) - self._max_visible,
        ))
        end = min(start + self._max_visible, len(display))

        max_label_w = min(30, max(visible_width(it.label) for it in self._items))

        for i in range(start, end):
            item = display[i]
            is_sel = i == self._selected_index
            prefix = self._theme.cursor if is_sel else "  "
            prefix_w = visible_width(prefix)

            label_padded = item.label + " " * max(0, max_label_w - visible_width(item.label))
            label_text = self._theme.label(label_padded, is_sel)

            sep = "  "
            used_w = prefix_w + max_label_w + visible_width(sep)
            val_max_w = width - used_w - 2
            val_text = self._theme.value(
                truncate_to_width(item.current_value, val_max_w, ""), is_sel
            )
            lines.append(truncate_to_width(prefix + label_text + sep + val_text, width))

        if start > 0 or end < len(display):
            scroll_text = f"  ({self._selected_index + 1}/{len(display)})"
            lines.append(self._theme.hint(truncate_to_width(scroll_text, width - 2, "")))

        sel_item = display[self._selected_index] if self._selected_index < len(display) else None
        if sel_item and sel_item.description:
            lines.append("")
            for ln in wrap_text_with_ansi(sel_item.description, width - 4):
                lines.append(self._theme.description(f"  {ln}"))

        self._add_hint_line(lines, width)
        return lines

    async def handle_input(self, data: str) -> None:
        if self._submenu_component:
            if hasattr(self._submenu_component, "handle_input"):
                await self._submenu_component.handle_input(data)
            return

        kb = get_editor_keybindings()
        display = self._filtered_items if self._search_enabled else self._items

        if kb.matches(data, "tui.select.up"):
            if display:
                self._selected_index = (
                    len(display) - 1 if self._selected_index == 0 else self._selected_index - 1
                )
        elif kb.matches(data, "tui.select.down"):
            if display:
                self._selected_index = (
                    0 if self._selected_index == len(display) - 1 else self._selected_index + 1
                )
        elif kb.matches(data, "tui.select.confirm") or data == " ":
            await self._activate_item()
        elif kb.matches(data, "tui.select.cancel"):
            await self._on_cancel()
        elif self._search_enabled and self._search_input:
            sanitized = data.replace(" ", "")
            if not sanitized:
                return
            await self._search_input.handle_input(sanitized)
            self._apply_filter(self._search_input.get_value())

    async def _activate_item(self) -> None:
        display = self._filtered_items if self._search_enabled else self._items
        if self._selected_index >= len(display):
            return
        item = display[self._selected_index]

        if item.submenu:
            self._submenu_item_index = self._selected_index

            async def done(selected_value: str | None = None) -> None:
                if selected_value is not None:
                    item.current_value = selected_value
                    await self._on_change(item.id, selected_value)
                self._close_submenu()

            self._submenu_component = item.submenu(item.current_value, done)
        elif item.values:
            idx = item.values.index(item.current_value) if item.current_value in item.values else -1
            new_idx = (idx + 1) % len(item.values)
            item.current_value = item.values[new_idx]
            await self._on_change(item.id, item.current_value)

    def _close_submenu(self) -> None:
        self._submenu_component = None
        if self._submenu_item_index is not None:
            self._selected_index = self._submenu_item_index
            self._submenu_item_index = None

    def _apply_filter(self, query: str) -> None:
        self._filtered_items = fuzzy_filter(self._items, query, lambda it: it.label)
        self._selected_index = 0

    def _add_hint_line(self, lines: list[str], width: int) -> None:
        lines.append("")
        hint = (
            "  Type to search · Enter/Space to change · Esc to cancel"
            if self._search_enabled
            else "  Enter/Space to change · Esc to cancel"
        )
        lines.append(truncate_to_width(self._theme.hint(hint), width))
