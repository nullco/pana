"""``/login`` command — authenticates with a provider."""
from __future__ import annotations

from pana.ai.providers.factory import get_provider, get_providers
from pana.app import ui_themes
from pana.app.commands.base import Command
from pana.app.context import UIContext
from pana.tui.components.select_list import SelectItem, SelectList


class LoginCommand(Command):
    name = "login"
    aliases = []
    description = "Authenticate with a provider"

    async def execute(self, ctx: UIContext, args: str) -> None:
        providers = get_providers()
        if not providers:
            ctx.notify("No providers available.", "error")
            return

        items = [SelectItem(value=p, label=p) for p in providers]
        select = SelectList(items, 5, ui_themes.select_list_theme, searchable=True)
        restore = ctx.show_selector(select)

        async def on_select(item: SelectItem) -> None:
            restore()

            async def handler(message: str) -> None:
                ctx.notify(message, "muted")

            try:
                await get_provider(item.value).authenticate(handler)
            except Exception as e:
                ctx.notify(f"Auth failed: {e}", "error")

        async def on_cancel() -> None:
            restore()

        select.on_select = on_select
        select.on_cancel = on_cancel
