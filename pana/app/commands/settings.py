"""``/settings`` command — configure thinking level, visibility, and theme."""
from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Callable

from pana.agents.agent import THINKING_LEVELS
from pana.app import theme as _theme
from pana.app import ui_themes
from pana.app.commands.base import Command
from pana.tui.tui import UIContext
from pana.state import state
from pana.tui.components.select_list import SelectItem, SelectList
from pana.tui.components.settings_list import SettingItem, SettingsList
from pana.tui.theme import discover_themes

logger = logging.getLogger(__name__)


class SettingsCommand(Command):
    name = "settings"
    aliases = []
    description = "Configure thinking level, display options, and theme"

    async def execute(self, ctx: UIContext, args: str) -> None:
        current_theme_name = state.get("theme", "dark")

        def _theme_submenu(
            current_value: str,
            done: Callable[[str | None], Awaitable[None]],
        ) -> SelectList:
            """Build a SelectList of all discoverable themes."""
            theme_paths = discover_themes()
            sel_items = [
                SelectItem(
                    value=name,
                    label=(
                        f"{name}  {_theme.dim('← active')}"
                        if name == current_value
                        else f"{name}  {_theme.dim(str(theme_paths[name].parent))}"
                    ),
                )
                for name in sorted(theme_paths)
            ]
            select = SelectList(sel_items, 8, ui_themes.select_list_theme, searchable=True)

            async def on_select(item: SelectItem) -> None:
                await done(item.value)

            async def on_cancel() -> None:
                await done(None)

            select.on_select = on_select
            select.on_cancel = on_cancel
            return select

        items = [
            SettingItem(
                id="thinking_level",
                label="Thinking level",
                current_value=state.get("thinking_level", "medium"),
                description="Reasoning depth for thinking-capable models",
                values=list(THINKING_LEVELS),
            ),
            SettingItem(
                id="hide_thinking_block",
                label="Hide thinking",
                current_value="true" if state.get("hide_thinking_block", False) else "false",
                description="Hide thinking blocks in assistant responses",
                values=["false", "true"],
            ),
            SettingItem(
                id="theme",
                label="Theme",
                current_value=current_theme_name,
                description=(
                    "Color theme for the UI. "
                    "Built-in: dark, light. "
                    "Custom themes: ~/.pana/themes/*.json or .pana/themes/*.json"
                ),
                submenu=_theme_submenu,
            ),
        ]

        async def on_change(setting_id: str, value: str) -> None:
            if setting_id == "thinking_level":
                state.set("thinking_level", value)
                if ctx.agent is not None:
                    ctx.agent.set_thinking_level(value)
                ctx.update_footer()
            elif setting_id == "hide_thinking_block":
                ctx.set_hide_thinking_block(value == "true")
            elif setting_id == "theme":
                try:
                    ui_themes.apply_theme(value)
                    state.set("theme", value)
                    ctx.request_render()
                except Exception as exc:
                    logger.warning("Failed to apply theme '%s': %s", value, exc)
            ctx.request_render()

        async def on_cancel() -> None:
            restore()

        settings_list = SettingsList(
            items,
            max_visible=8,
            theme=ui_themes.get_settings_theme(),
            on_change=on_change,
            on_cancel=on_cancel,
        )
        restore = ctx.show_selector(settings_list)
