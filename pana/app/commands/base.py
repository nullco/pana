"""Base abstractions for the slash-command system.

Third-party code only needs to import from this module to add new commands:

    from pana.app.commands.base import Command
    from pana.app.context import UIContext

    class MyCommand(Command):
        name = "mycommand"
        description = "Does something cool"

        async def execute(self, ctx: UIContext, args: str) -> None:
            ctx.add_message(...)
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from pana.app.context import UIContext


class Command(ABC):
    """Base class for every slash command.

    Sub-class this, set the class attributes, and implement
    :meth:`execute`.  Register an instance with a
    :class:`~pana.app.commands.registry.CommandRegistry` to make it
    available at runtime.

    Example::

        class VersionCommand(Command):
            name = "version"
            description = "Print the current pana version"

            async def execute(self, ctx: UIContext, args: str) -> None:
                from pana import __version__
                from pana.tui.components.text import Text
                ctx.add_message(Text(__version__, padding_x=1, padding_y=0))
    """

    #: Primary name used to invoke the command (without the leading ``/``).
    name: str

    #: Alternative names that also resolve to this command (no leading ``/``).
    aliases: list[str] = []

    #: One-line description shown in ``/help`` and the autocomplete popup.
    description: str

    @abstractmethod
    async def execute(self, ctx: UIContext, args: str) -> None:
        """Run the command.

        Parameters
        ----------
        ctx:
            Application context providing UI helpers and state accessors.
        args:
            Everything the user typed *after* the command name, stripped of
            leading/trailing whitespace.  Empty string when the user typed the
            command alone.
        """
