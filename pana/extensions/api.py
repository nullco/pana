"""Core types and classes for the Pana extension API.

Extension authors import from this module::

    from pana.extensions.api import ExtensionAPI, ExtensionContext, ToolDefinition, CommandDefinition
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from pana.tui.tui import UIContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shell execution helper
# ---------------------------------------------------------------------------


@dataclass
class ExecResult:
    """Result of a shell command executed via :meth:`ExtensionAPI.exec`."""

    stdout: str
    stderr: str
    code: int
    killed: bool = False


# ---------------------------------------------------------------------------
# Tool and command definitions
# ---------------------------------------------------------------------------


@dataclass
class ToolDefinition:
    """Definition of a custom tool registered by an extension.

    The ``execute`` function's type annotations define the tool's parameter
    schema — pydantic-ai introspects the function signature to build the JSON
    schema for the LLM.  The docstring is used as the tool description if
    ``description`` is not supplied.

    Example::

        async def my_tool(path: str, count: int = 1) -> str:
            \"\"\"Do something with a file.\"\"\"
            return "done"

        pana.register_tool(ToolDefinition(
            name="my_tool",
            description="Do something with a file",
            execute=my_tool,
        ))
    """

    name: str
    execute: Callable[..., Coroutine[Any, Any, str]]
    description: str = ""
    label: str = ""


@dataclass
class CommandDefinition:
    """Definition of a slash command registered by an extension.

    The ``handler`` is called with ``(args: str, ctx: ExtensionContext)``
    when the user runs the command.
    """

    description: str
    handler: Callable[..., Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# Extension context
# ---------------------------------------------------------------------------


@dataclass
class ExtensionContext:
    """Context object passed to every extension event handler and command handler.

    Attributes:
        cwd:    Current working directory.
        ui:     Full UI context (see :class:`~pana.tui.tui.UIContext`).
        signal: The active agent cancellation event, or ``None`` outside a run.
    """

    cwd: str
    ui: UIContext
    signal: asyncio.Event | None = None


# ---------------------------------------------------------------------------
# Event data-classes
# ---------------------------------------------------------------------------


@dataclass
class SessionStartEvent:
    """Fired once when the application session begins."""


@dataclass
class SessionShutdownEvent:
    """Fired when the application is about to exit."""


@dataclass
class InputEvent:
    """Fired when the user submits text, before command dispatch.

    Handlers may return:

    * ``{"action": "continue"}``  — pass the text through unchanged (default).
    * ``{"action": "transform", "text": "…"}``  — replace the input text.
    * ``{"action": "handled"}``  — stop processing; do not run the agent.
    """

    text: str
    source: str = "interactive"  # "interactive" | "extension"


@dataclass
class BeforeAgentStartEvent:
    """Fired after input processing, before the agent loop starts.

    Handlers may return ``{"system_prompt": "extra text"}`` to append
    additional instructions to the system prompt for this turn only.
    """

    prompt: str
    system_prompt: str = ""


@dataclass
class AgentStartEvent:
    """Fired once per user prompt, just before the agent loop begins."""

    prompt: str


@dataclass
class AgentEndEvent:
    """Fired once per user prompt, after the agent loop completes."""

    prompt: str


@dataclass
class TurnStartEvent:
    """Fired at the start of each LLM request turn."""

    turn_index: int


@dataclass
class TurnEndEvent:
    """Fired after each round of tool execution completes."""

    turn_index: int


@dataclass
class ToolCallEvent:
    """Fired before a tool executes.

    Handlers may return ``{"block": True, "reason": "…"}`` to prevent
    execution.  The ``input`` dict is mutable — modifications affect the
    actual tool call.
    """

    tool_name: str
    input: dict = field(default_factory=dict)


@dataclass
class ToolResultEvent:
    """Fired after a tool completes, before the result is sent to the LLM.

    Handlers may return ``{"content": "…"}`` to replace the result text.
    """

    tool_name: str
    input: dict
    content: str
    is_error: bool = False


# ---------------------------------------------------------------------------
# ExtensionAPI
# ---------------------------------------------------------------------------


class ExtensionAPI:
    """API object passed to each extension's ``setup()`` function.

    Each loaded extension receives its own ``ExtensionAPI`` instance.

    Example extension (``~/.pana/extensions/my_ext.py``)::

        from pana.extensions.api import ExtensionAPI, ToolDefinition, CommandDefinition

        def setup(pana: ExtensionAPI) -> None:
            @pana.on("session_start")
            async def on_start(event, ctx):
                ctx.ui.notify("Extension loaded!", "info")

            pana.on("tool_call", lambda event, ctx: (
                {"block": True, "reason": "rm -rf blocked"}
                if event.tool_name == "bash" and "rm -rf" in event.input.get("command", "")
                else None
            ))

            pana.register_command("hello", CommandDefinition(
                description="Say hello",
                handler=lambda args, ctx: ctx.ui.notify(f"Hello {args or 'world'}!"),
            ))
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {}
        self._tools: list[ToolDefinition] = []
        self._commands: dict[str, CommandDefinition] = {}

    def on(self, event: str, handler: Callable | None = None) -> Callable:
        """Subscribe *handler* to *event*.

        May be used as a plain call or as a decorator::

            pana.on("session_start", my_handler)

            @pana.on("tool_call")
            async def guard(event, ctx):
                ...

        Args:
            event:   Event name (e.g. ``"tool_call"``, ``"session_start"``).
            handler: Callable to register.  When used as a decorator, omit
                     this argument and the decorated function is registered.

        Returns:
            The handler (for decorator usage).
        """
        if handler is not None:
            self._handlers.setdefault(event, []).append(handler)
            return handler

        # Decorator form: @pana.on("event")
        def decorator(fn: Callable) -> Callable:
            self._handlers.setdefault(event, []).append(fn)
            return fn

        return decorator

    def register_tool(self, definition: ToolDefinition) -> None:
        """Register a custom tool the LLM can call.

        Args:
            definition: :class:`ToolDefinition` with name, execute function,
                        and optional description/label.
        """
        self._tools.append(definition)

    def register_command(self, name: str, definition: CommandDefinition) -> None:
        """Register a slash command.

        Args:
            name:       Command name without the leading ``/``.
            definition: :class:`CommandDefinition` with description and handler.
        """
        self._commands[name] = definition

    async def exec(
        self,
        command: str,
        args: list[str] | None = None,
        *,
        signal: asyncio.Event | None = None,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        """Execute a shell command and return its output.

        Args:
            command: Executable to run.
            args:    Optional argument list.
            signal:  Cancellation event.
            timeout: Timeout in seconds.
            cwd:     Working directory (defaults to ``Path.cwd()``).

        Returns:
            :class:`ExecResult` with stdout, stderr, exit code, and killed flag.
        """
        effective_cwd = cwd or str(Path.cwd())
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                command,
                *(args or []),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=effective_cwd,
            )

            comm_coro = proc.communicate()

            if signal is not None:
                cancel_task: asyncio.Future = asyncio.ensure_future(signal.wait())
                comm_task: asyncio.Future = asyncio.ensure_future(comm_coro)
                try:
                    done, _ = await asyncio.wait(
                        {cancel_task, comm_task},
                        timeout=timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    if not cancel_task.done():
                        cancel_task.cancel()

                if cancel_task in done:
                    comm_task.cancel()
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    return ExecResult(stdout="", stderr="Cancelled", code=-1, killed=True)

                if not comm_task.done():
                    comm_task.cancel()
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    return ExecResult(stdout="", stderr="Timed out", code=-1, killed=True)

                stdout_bytes, stderr_bytes = comm_task.result()
            else:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(comm_coro, timeout=timeout)

            return ExecResult(
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                code=proc.returncode or 0,
            )

        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except OSError:
                    pass
            return ExecResult(stdout="", stderr="Timed out", code=-1, killed=True)
        except Exception as exc:
            return ExecResult(stdout="", stderr=str(exc), code=-1)
