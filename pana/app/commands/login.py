"""``/login`` command — authenticates with a provider."""
from __future__ import annotations

from pana.ai.providers.factory import get_provider, get_providers
from pana.app.commands.base import Command
from pana.app.context import UIContext


class LoginCommand(Command):
    name = "login"
    aliases = []
    description = "Authenticate with a provider"

    async def execute(self, ctx: UIContext, args: str) -> None:
        providers = get_providers()
        if not providers:
            ctx.notify("No providers available.", "error")
            return

        chosen = await ctx.select("Select provider", list(providers))
        if chosen is None:
            return

        async def handler(message: str) -> None:
            ctx.notify(message, "muted")

        try:
            await get_provider(chosen).authenticate(handler)
        except Exception as e:
            ctx.notify(f"Auth failed: {e}", "error")
