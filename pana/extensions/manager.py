"""ExtensionManager — coordinates loaded extensions and dispatches lifecycle events.

Usage::

    manager = ExtensionManager(notify_fn=app.notify)

    api = ExtensionAPI()
    load_extension(path, api)
    manager.add_api(api)

    ctx = manager.make_context()
    await manager.emit("session_start", SessionStartEvent(), ctx)

    # Build pydantic-ai–compatible tool functions:
    tools = manager.build_all_tools(cancel_event_getter)

    # Build Command objects for the command registry:
    commands = manager.build_command_objects()
"""

from __future__ import annotations

import asyncio
import functools
import logging
from pathlib import Path
from typing import Any, Callable

from pana.extensions.api import (
    CommandDefinition,
    ExtensionAPI,
    ExtensionContext,
    ToolDefinition,
)
from pana.tui.tui import UIContext

logger = logging.getLogger(__name__)


class ExtensionManager:
    """Holds all loaded :class:`~pana.extensions.api.ExtensionAPI` instances
    and dispatches events to their registered handlers.
    """

    def __init__(self, ui: UIContext) -> None:
        self._ui = ui
        self._apis: list[ExtensionAPI] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add_api(self, api: ExtensionAPI) -> None:
        """Register a loaded extension API instance."""
        self._apis.append(api)

    @property
    def has_extensions(self) -> bool:
        """``True`` if at least one extension has been loaded."""
        return bool(self._apis)

    # ------------------------------------------------------------------
    # Context factory
    # ------------------------------------------------------------------

    def make_context(self, signal: asyncio.Event | None = None) -> ExtensionContext:
        """Create an :class:`~pana.extensions.api.ExtensionContext` for callbacks."""
        return ExtensionContext(
            cwd=str(Path.cwd()),
            ui=self._ui,
            signal=signal,
        )

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    async def emit(
        self,
        event: str,
        event_data: Any,
        ctx: ExtensionContext,
    ) -> Any:
        """Emit *event* to all registered handlers across all loaded extensions.

        Handlers are called in extension-load order, then in registration order
        within each extension.  The *last* non-``None`` return value from any
        handler is returned to the caller; earlier return values are shadowed by
        later ones.

        Exceptions inside handlers are logged and swallowed so that a broken
        extension cannot crash the agent.
        """
        result = None
        for api in self._apis:
            for handler in api._handlers.get(event, []):
                try:
                    ret = handler(event_data, ctx)
                    if asyncio.iscoroutine(ret):
                        ret = await ret
                    if ret is not None:
                        result = ret
                except Exception:
                    logger.exception(
                        "Error in extension handler %r for event %r", handler, event
                    )
        return result

    # ------------------------------------------------------------------
    # Tool helpers
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[ToolDefinition]:
        """Return all :class:`~pana.extensions.api.ToolDefinition` objects
        registered across all loaded extensions.
        """
        tools: list[ToolDefinition] = []
        for api in self._apis:
            tools.extend(api._tools)
        return tools

    def build_pydantic_tool(
        self,
        definition: ToolDefinition,
        cancel_event_getter: Callable[[], asyncio.Event | None],
    ) -> Callable:
        """Convert a :class:`~pana.extensions.api.ToolDefinition` into a
        pydantic-ai–compatible async function.

        The returned callable:

        * Has the same parameter signature as ``definition.execute`` (so
          pydantic-ai can derive the JSON schema for the LLM).
        * Uses ``definition.name`` as ``__name__`` and ``definition.description``
          (or the original docstring) as ``__doc__``.
        * Fires ``tool_call`` before execution and ``tool_result`` after.
        """
        execute_fn = definition.execute
        manager_ref = self

        @functools.wraps(execute_fn)
        async def wrapper(**kwargs: Any) -> str:
            ctx = manager_ref.make_context(signal=cancel_event_getter())

            tool_call_event = _make_tool_call_event(definition.name, kwargs)
            block = await manager_ref.emit("tool_call", tool_call_event, ctx)
            if isinstance(block, dict) and block.get("block"):
                return f"Error: {block.get('reason', 'Blocked by extension')}"

            # Run the original, which may be sync or async
            try:
                if asyncio.iscoroutinefunction(execute_fn):
                    result: str = await execute_fn(**kwargs)
                else:
                    result = execute_fn(**kwargs)
            except Exception as exc:
                result = f"Error: {exc}"

            tool_result_event = _make_tool_result_event(
                definition.name, kwargs, result
            )
            modified = await manager_ref.emit("tool_result", tool_result_event, ctx)
            if isinstance(modified, dict) and "content" in modified:
                return str(modified["content"])
            return result

        wrapper.__name__ = definition.name
        wrapper.__doc__ = definition.description or execute_fn.__doc__ or ""
        return wrapper

    def wrap_builtin_tool(
        self,
        original_fn: Callable,
        tool_name: str,
        cancel_event_getter: Callable[[], asyncio.Event | None],
    ) -> Callable:
        """Wrap a built-in tool function with ``tool_call`` / ``tool_result`` events.

        The wrapper preserves the original function's signature via
        ``functools.wraps`` so that pydantic-ai introspects the correct
        parameter schema.
        """
        manager_ref = self

        @functools.wraps(original_fn)
        async def wrapper(**kwargs: Any) -> str:
            ctx = manager_ref.make_context(signal=cancel_event_getter())

            tool_call_event = _make_tool_call_event(tool_name, kwargs)
            block = await manager_ref.emit("tool_call", tool_call_event, ctx)
            if isinstance(block, dict) and block.get("block"):
                return f"Error: {block.get('reason', 'Blocked by extension')}"

            try:
                if asyncio.iscoroutinefunction(original_fn):
                    result: str = await original_fn(**kwargs)
                else:
                    result = original_fn(**kwargs)
            except Exception as exc:
                result = f"Error: {exc}"

            tool_result_event = _make_tool_result_event(tool_name, kwargs, result)
            modified = await manager_ref.emit("tool_result", tool_result_event, ctx)
            if isinstance(modified, dict) and "content" in modified:
                return str(modified["content"])
            return result

        return wrapper

    def build_all_tools(
        self,
        builtin_fns: list[Callable],
        builtin_names: list[str],
        cancel_event_getter: Callable[[], asyncio.Event | None],
    ) -> list[Callable]:
        """Return the full tool list: wrapped built-ins + extension tools.

        Args:
            builtin_fns:          Original built-in tool functions.
            builtin_names:        Logical names for each built-in (e.g. ``"bash"``).
            cancel_event_getter:  Zero-arg callable returning the current cancel event.
        """
        tools: list[Callable] = []
        for fn, name in zip(builtin_fns, builtin_names):
            tools.append(self.wrap_builtin_tool(fn, name, cancel_event_getter))
        for defn in self.get_tool_definitions():
            tools.append(self.build_pydantic_tool(defn, cancel_event_getter))
        return tools

    # ------------------------------------------------------------------
    # Command helpers
    # ------------------------------------------------------------------

    def get_command_definitions(self) -> dict[str, CommandDefinition]:
        """Return all command definitions registered by extensions.

        When multiple extensions register the same name, the last one wins.
        """
        commands: dict[str, CommandDefinition] = {}
        for api in self._apis:
            commands.update(api._commands)
        return commands

    def build_command_objects(self) -> list[object]:
        """Build :class:`~pana.app.commands.base.Command` instances from
        every extension-registered command definition.

        Importing is deferred to avoid a circular dependency.
        """
        from pana.app.commands.base import Command

        objects: list[Command] = []
        for cmd_name, defn in self.get_command_definitions().items():
            objects.append(_make_ext_command(cmd_name, defn, self))
        return objects


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _make_tool_call_event(tool_name: str, kwargs: dict) -> object:
    from pana.extensions.api import ToolCallEvent

    return ToolCallEvent(tool_name=tool_name, input=dict(kwargs))


def _make_tool_result_event(tool_name: str, kwargs: dict, content: str) -> object:
    from pana.extensions.api import ToolResultEvent

    return ToolResultEvent(
        tool_name=tool_name,
        input=dict(kwargs),
        content=content,
        is_error=content.lstrip().startswith("Error"),
    )


def _make_ext_command(cmd_name: str, defn: "CommandDefinition", manager: "ExtensionManager") -> object:
    """Create a concrete :class:`~pana.app.commands.base.Command` for an extension command.

    The class is built dynamically so that ``execute`` is defined *inside* the
    class body, satisfying Python's ABCMeta abstract-method check.
    """
    from pana.app.commands.base import Command

    _handler = defn.handler
    _manager = manager

    class _ExtCommand(Command):
        name = cmd_name
        description = defn.description

        async def execute(self, ctx: UIContext, args: str) -> None:
            ext_ctx = _manager.make_context()
            ret = _handler(args, ext_ctx)
            if asyncio.iscoroutine(ret):
                await ret

    return _ExtCommand()
