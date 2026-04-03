"""``/new`` command — clears the chat history and starts a fresh session."""
from __future__ import annotations

from pana.app import theme as _theme
from pana.app.commands.base import Command
from pana.app.context import UIContext
from pana.tui.components.text import Text


class NewCommand(Command):
    name = "new"
    aliases = []
    description = "Start a new session"

    async def execute(self, ctx: UIContext, args: str) -> None:
        ctx.clear_chat()
        ctx.add_message(Text(_theme.dim("✓ New session started"), padding_x=1, padding_y=0))
        ctx.request_render()
