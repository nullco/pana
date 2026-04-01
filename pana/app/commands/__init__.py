"""``pana.app.commands`` — the slash-command system.

Built-in commands are registered in :data:`default_registry`.  Third-party
code can register additional commands there::

    from pana.app.commands import default_registry
    from pana.app.commands.base import Command, CommandContext

    class GreetCommand(Command):
        name = "greet"
        description = "Say hello"

        async def execute(self, ctx: CommandContext, args: str) -> None:
            from pana.tui.components.text import Text
            ctx.add_message(Text(f"Hello, {args or 'world'}!", padding_x=1, padding_y=0))

    default_registry.register(GreetCommand())
"""
from __future__ import annotations

from pana.app.commands.base import Command, CommandContext
from pana.app.commands.registry import CommandRegistry

# Avoid importing the concrete command modules at the top level so that the
# package stays importable even when optional dependencies are missing.  The
# factory function below does the real work.


def _build_default_registry() -> CommandRegistry:
    # Deferred imports keep startup fast and avoid any circular-import risk.
    from pana.app.commands.help import HelpCommand
    from pana.app.commands.login import LoginCommand
    from pana.app.commands.model import ModelCommand
    from pana.app.commands.new import NewCommand
    from pana.app.commands.quit import QuitCommand
    from pana.app.commands.settings import SettingsCommand

    registry = CommandRegistry()

    # Registration order determines the order shown in /help.
    registry.register(LoginCommand())
    registry.register(ModelCommand())
    registry.register(SettingsCommand())
    registry.register(NewCommand())
    registry.register(HelpCommand(registry))
    registry.register(QuitCommand())

    return registry


#: The application-wide command registry.  Register custom commands here.
default_registry: CommandRegistry = _build_default_registry()

__all__ = [
    "Command",
    "CommandContext",
    "CommandRegistry",
    "default_registry",
]
