"""Command registry with prefix-matching dispatch."""
from __future__ import annotations

import logging

from pana.app.commands.base import Command
from pana.tui.tui import UIContext

logger = logging.getLogger(__name__)


class CommandRegistry:
    """Holds :class:`~pana.app.commands.base.Command` instances and dispatches
    slash-command input.

    Usage::

        registry = CommandRegistry()
        registry.register(MyCommand())

        # In your input handler:
        handled = await registry.dispatch("/mycommand some args", ctx)
        if not handled:
            ...  # not a known command

    Commands are resolved by their :attr:`~Command.name` and any
    :attr:`~Command.aliases`.  Prefix matching is supported as long as the
    prefix is unambiguous across all registered names *and* aliases.
    """

    def __init__(self) -> None:
        # Maps every name/alias → Command instance.
        self._by_name: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        """Register *command* under its name and all aliases."""
        self._by_name[command.name] = command
        for alias in command.aliases:
            self._by_name[alias] = command

    def resolve(self, name: str) -> Command | None:
        """Return the command whose name (or alias) matches *name*.

        Exact match wins; otherwise tries unique-prefix matching across all
        registered names *and* aliases.  Returns ``None`` when no match or
        when the prefix is ambiguous.
        """
        name = name.lstrip("/").lower()
        if name in self._by_name:
            return self._by_name[name]

        # Prefix matching — deduplicate by primary name to avoid counting the
        # same command twice when it has aliases that share the prefix.
        matched: dict[str, Command] = {}
        for key, cmd in self._by_name.items():
            if key.startswith(name):
                matched[cmd.name] = cmd

        return next(iter(matched.values())) if len(matched) == 1 else None

    async def dispatch(self, text: str, ctx: UIContext) -> bool:
        """Parse *text* as a slash command and execute it.

        Returns ``True`` when a command was found and executed, ``False``
        when *text* is not a recognised slash command (so the caller can treat
        it as a plain chat message or show an error).
        """
        if not text.startswith("/"):
            return False

        parts = text.lstrip("/").split(None, 1)
        cmd_name = parts[0].lower() if parts else ""
        args = parts[1].strip() if len(parts) > 1 else ""

        command = self.resolve(cmd_name)
        if command is None:
            return False

        logger.debug("Dispatching command /%s with args=%r", cmd_name, args)
        await command.execute(ctx, args)
        return True

    def all_commands(self) -> list[Command]:
        """Return a deduplicated list of every registered :class:`Command`."""
        seen: dict[str, Command] = {}
        for cmd in self._by_name.values():
            seen[cmd.name] = cmd
        return list(seen.values())

    def completions(self) -> dict[str, str]:
        """Return ``{name: description}`` for autocomplete (primary names only)."""
        return {cmd.name: cmd.description for cmd in self.all_commands()}
