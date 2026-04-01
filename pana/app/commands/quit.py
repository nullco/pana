"""``/quit`` command — exits the application."""
from __future__ import annotations

from pana.app.commands.base import Command, CommandContext


class QuitCommand(Command):
    name = "quit"
    aliases = ["exit", "q"]
    description = "Exit"

    async def execute(self, ctx: CommandContext, args: str) -> None:
        ctx.stop()
