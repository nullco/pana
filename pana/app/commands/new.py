"""``/new`` command — clears the chat history and starts a fresh session."""
from __future__ import annotations

from pana.app.commands.base import Command
from pana.app.context import UIContext


class NewCommand(Command):
    name = "new"
    aliases = []
    description = "Start a new session"

    async def execute(self, ctx: UIContext, args: str) -> None:
        ctx.clear_chat()
        ctx.notify("✓ New session started", "muted")
