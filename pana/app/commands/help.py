"""``/help`` command — lists every registered command."""
from __future__ import annotations

from pana.app import theme as _theme
from pana.app.commands.base import Command
from pana.app.context import UIContext
from pana.tui.components.spacer import Spacer
from pana.tui.components.text import Text

if False:  # TYPE_CHECKING — avoid circular import
    from pana.app.commands.registry import CommandRegistry


class HelpCommand(Command):
    name = "help"
    aliases = []
    description = "Show available commands"

    def __init__(self, registry: CommandRegistry) -> None:  # type: ignore[name-defined]
        self._registry = registry

    async def execute(self, ctx: UIContext, args: str) -> None:
        lines = [_theme.bold("Commands:")]
        for cmd in self._registry.all_commands():
            name_col = f"/{cmd.name:<8}"
            alias_hint = (
                f"  {_theme.dim('(' + ', '.join('/' + a for a in cmd.aliases) + ')')}"
                if cmd.aliases
                else ""
            )
            lines.append(f"  {_theme.accent(name_col)} — {cmd.description}{alias_hint}")
        ctx.add_message(Text("\n".join(lines), padding_x=1, padding_y=0))
        ctx.add_message(Spacer(1))
