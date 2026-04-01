"""``/login`` command — authenticates with a provider."""
from __future__ import annotations

from pana.ai.providers.factory import get_provider, get_providers
from pana.app import theme as _theme
from pana.app import ui_themes
from pana.app.commands.base import Command, CommandContext
from pana.tui.components.select_list import SelectItem, SelectList
from pana.tui.components.spacer import Spacer
from pana.tui.components.text import Text


class LoginCommand(Command):
    name = "login"
    aliases = []
    description = "Authenticate with a provider"

    async def execute(self, ctx: CommandContext, args: str) -> None:
        providers = get_providers()
        if not providers:
            ctx.add_message(Text(_theme.error("No providers available."), padding_x=1, padding_y=0))
            ctx.add_message(Spacer(1))
            return

        items = [SelectItem(value=p, label=p) for p in providers]
        select = SelectList(items, 5, ui_themes.select_list_theme, searchable=True)
        restore = ctx.show_selector(select)

        async def on_select(item: SelectItem) -> None:
            restore()
            try:
                await get_provider(item.value).authenticate(lambda result: None)
                ctx.add_message(
                    Text(
                        _theme.success(f"Authenticated with {item.value}."),
                        padding_x=1,
                        padding_y=0,
                    )
                )
            except Exception as e:
                ctx.add_message(Text(_theme.error(f"Auth failed: {e}"), padding_x=1, padding_y=0))
            ctx.add_message(Spacer(1))

        async def on_cancel() -> None:
            restore()

        select.on_select = on_select
        select.on_cancel = on_cancel
