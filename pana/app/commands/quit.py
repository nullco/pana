"""``/quit`` command — exits the application."""
from __future__ import annotations

from pana.app.commands.base import Command
from pana.tui.tui import UIContext


class QuitCommand(Command):
    name = "quit"
    aliases = ["exit", "q"]
    description = "Exit"

    async def execute(self, ctx: UIContext, args: str) -> None:
        ctx.stop()
