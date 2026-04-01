"""Base abstractions for the slash-command system.

Third-party code only needs to import from this module to add new commands:

    from pana.app.commands.base import Command, CommandContext

    class MyCommand(Command):
        name = "mycommand"
        description = "Does something cool"

        async def execute(self, ctx: CommandContext, args: str) -> None:
            ctx.add_message(...)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pana.agents.agent import Agent


@runtime_checkable
class CommandContext(Protocol):
    """Minimal interface that the host application must satisfy.

    :class:`~pana.main.MiniApp` implements every method here.  External code
    that creates commands should type its *ctx* parameter as
    ``CommandContext`` so it stays decoupled from the concrete app class.
    """

    @property
    def agent(self) -> Agent | None:
        """The currently active LLM agent, or ``None`` if none is selected."""
        ...

    @property
    def hide_thinking_block(self) -> bool:
        """Whether thinking blocks are hidden in the chat view."""
        ...

    def add_message(self, component: Any) -> None:
        """Append *component* to the chat scroll area and re-render."""
        ...

    def show_selector(
        self, component: Any, focus_target: Any = None
    ) -> Callable[[], None]:
        """Swap the editor area for *component* and return a ``restore`` callable.

        Calling the returned function removes the selector and brings back
        the normal editor.
        """
        ...

    def update_footer(self) -> None:
        """Refresh the footer (model name, thinking level, …)."""
        ...

    def clear_chat(self) -> None:
        """Remove all chat messages, keeping only the header row."""
        ...

    def stop(self) -> None:
        """Shut down the TUI and exit the application."""
        ...

    def request_render(self) -> None:
        """Ask the TUI for an immediate re-render."""
        ...

    def set_agent(self, agent: Agent) -> None:
        """Replace the active agent with *agent*."""
        ...

    def set_hide_thinking_block(self, value: bool) -> None:
        """Toggle thinking-block visibility and persist to state."""
        ...


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

            async def execute(self, ctx: CommandContext, args: str) -> None:
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
    async def execute(self, ctx: CommandContext, args: str) -> None:
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
