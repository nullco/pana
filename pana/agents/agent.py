import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic_ai._agent_graph import CallToolsNode, End, ModelRequestNode
from pydantic_ai.agent import Agent as PydanticAgent
from pydantic_ai.messages import TextPart, ThinkingPart, ToolCallPart, ToolReturnPart
from pydantic_ai.settings import ModelSettings

from pana.agents.system_prompt import build_system_prompt
from pana.agents.tool_streams import (
    ToolStreamHandler,
    build_stream_handlers,
    try_extract_partial_args,
)
from pana.agents.tools import tool_bash, tool_edit, tool_read, tool_write
from pana.ai.providers.model import Model

logger = logging.getLogger(__name__)


class _CancelledByEvent(BaseException):
    """Raised inside node.stream()'s async-with body to trigger clean pydantic-ai
    teardown (stream_done.set + wrap_task.cancel) when the user cancels via an
    asyncio.Event rather than task.cancel().  Using a distinct BaseException
    subclass prevents it from being caught by broad ``except Exception`` clauses
    and clearly communicates intent.
    """


THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh")



@dataclass
class ToolCallEvent:
    """Fired as soon as the model commits to invoking a tool (args may be partial)."""

    tool_call_id: str | None
    tool_name: str
    args: dict | str | None


@dataclass
class ToolCallUpdateEvent:
    """Fired after a tool's arguments are fully received, to update an earlier ToolCallEvent."""

    tool_call_id: str | None
    tool_name: str
    args: dict | str | None


@dataclass
class ToolResultEvent:
    """Fired when a tool returns its result."""

    tool_call_id: str | None
    tool_name: str
    result: str
    elapsed_s: float | None = None
    is_error: bool = False


@dataclass
class TextEvent:
    """Fired for text content (streamed delta or final)."""

    text: str
    is_complete: bool = False


@dataclass
class ThinkingEvent:
    """Fired for thinking/reasoning content from the model."""

    text: str


StreamEvent = ToolCallEvent | ToolCallUpdateEvent | ToolResultEvent | TextEvent | ThinkingEvent



@dataclass
class _RunState:
    """Holds all mutable bookkeeping for a single agent run."""

    # Maps tool_call_id → monotonic start time, used to compute elapsed_s.
    call_started: dict[str, float] = field(default_factory=dict)
    # IDs for which an early ToolCallEvent has already been emitted during
    # ModelRequestNode streaming, so CallToolsNode knows to send an Update.
    emitted_early_ids: set[str] = field(default_factory=set)
    # Per-tool handlers that throttle how often partial-arg updates are emitted.
    stream_handlers: dict[str, ToolStreamHandler] = field(default_factory=build_stream_handlers)


class Agent:

    def __init__(self, model: Model, thinking_level: str = "medium") -> None:
        self._model = model
        self._thinking_level = thinking_level
        self._system_prompt = build_system_prompt()
        self._agent = self._build_agent()
        self._message_history = None

    def _build_agent(self) -> PydanticAgent:
        kwargs = {
            "model": self._model.instance,
            "tools": [tool_read, tool_edit, tool_write, tool_bash],
        }
        if self._system_prompt:
            kwargs["system_prompt"] = self._system_prompt
        return PydanticAgent(**kwargs)

    @property
    def model_name(self) -> str:
        return self._model.name

    @property
    def provider_name(self) -> str:
        return self._model.provider.name

    @property
    def thinking_level(self) -> str:
        return self._thinking_level

    def set_thinking_level(self, level: str) -> None:
        if level not in THINKING_LEVELS:
            raise ValueError(f"Invalid thinking level: {level!r}. Must be one of {THINKING_LEVELS}")
        self._thinking_level = level

    def _build_model_settings(self) -> ModelSettings | None:
        if not self._thinking_level or self._thinking_level == "off":
            return None
        return ModelSettings(
            thinking=self._thinking_level,
            openai_reasoning_summary="auto",
        )

    def set_model(self, model: Model) -> None:
        self._model = model
        self._agent = self._build_agent()

    def clear_history(self) -> None:
        self._message_history = None
        self._system_prompt = build_system_prompt()
        self._agent = self._build_agent()

    async def stream(
        self,
        user_input: str,
        event_handler: Callable[[StreamEvent], None],
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        """Run the agent and emit StreamEvents for text, thinking, and tool activity.

        Uses the pydantic-ai iter() graph API so we can interleave streamed text
        with tool call/result events.  See the private helpers below for the
        per-node logic.

        cancel_event: when set, exits the streaming loop cleanly at the next
        token boundary without task.cancel() — avoids pydantic-ai context-manager
        teardown issues and lets the caller restore the UI immediately.
        """
        await self._ensure_auth()
        state = _RunState()

        async with self._agent.iter(
                user_input,
                message_history=self._message_history,
                model_settings=self._build_model_settings(),
            ) as agent_run:
                try:
                    node = agent_run.next_node
                    while not isinstance(node, End):
                        if cancel_event and cancel_event.is_set():
                            break
                        if isinstance(node, ModelRequestNode):
                            node = await self._stream_model_request_node(
                                node, agent_run, state, event_handler, cancel_event
                            )
                        elif isinstance(node, CallToolsNode):
                            node = await self._process_call_tools_node(
                                node, agent_run, state, event_handler
                            )
                        else:
                            node = await agent_run.next(node)
                finally:
                    self._message_history = agent_run.all_messages()
    async def _ensure_auth(self) -> None:
        """Re-authenticate if the provider token is close to expiry."""
        if self._model.provider.should_reauthenticate():
            await self._model.provider.reauthenticate()
            model = await self._model.provider.build_model(self._model.name)
            self.set_model(model)

    async def _stream_model_request_node(
        self,
        node: ModelRequestNode,
        agent_run,
        state: _RunState,
        event_handler: Callable[[StreamEvent], None],
        cancel_event: asyncio.Event | None = None,
    ):
        """Stream a ModelRequestNode, emitting Text/Thinking/ToolCall events.

        Each response chunk races against cancel_event via asyncio.wait().  When
        the event fires, _CancelledByEvent is raised *inside* the async-with body
        so pydantic-ai's finally block (stream_done + wrap_task cleanup) always
        runs — no dangling tasks, no leaked HTTP connections, no context warnings.

        For app-exit task.cancel(), CancelledError hits the asyncio.wait() await
        inside the body (same safe zone), so pydantic-ai cleanup also runs there.
        """
        last_text = ""
        last_thinking = ""
        _user_cancelled = False

        try:
            async with node.stream(agent_run.ctx) as stream:
                # One persistent waiter for the cancel signal — reused across
                # all iterations so we don't create an extra task per token.
                cancel_waiter = (
                    asyncio.ensure_future(cancel_event.wait()) if cancel_event else None
                )
                try:
                    stream_iter = stream.stream_responses(debounce_by=0.05).__aiter__()
                    while True:
                        next_item = asyncio.ensure_future(stream_iter.__anext__())
                        waitables: set[asyncio.Future] = {next_item}
                        if cancel_waiter:
                            waitables.add(cancel_waiter)

                        done, _ = await asyncio.wait(
                            waitables, return_when=asyncio.FIRST_COMPLETED
                        )

                        if cancel_waiter in done:
                            # Cancel the pending network read, then signal
                            # pydantic-ai to tear down wrap_task cleanly.
                            next_item.cancel()
                            try:
                                await next_item
                            except BaseException:
                                pass
                            raise _CancelledByEvent()

                        try:
                            response = next_item.result()
                        except StopAsyncIteration:
                            break

                        cur_thinking = "".join(
                            p.content
                            for p in response.parts
                            if isinstance(p, ThinkingPart) and p.content
                        )
                        if cur_thinking and cur_thinking != last_thinking:
                            last_thinking = cur_thinking
                            event_handler(ThinkingEvent(text=cur_thinking))

                        cur_text = "".join(
                            p.content
                            for p in response.parts
                            if isinstance(p, TextPart) and p.content
                        )
                        if cur_text != last_text:
                            last_text = cur_text
                            event_handler(TextEvent(text=cur_text))

                        for part in response.parts:
                            if isinstance(part, ToolCallPart):
                                self._handle_streaming_tool_call(part, state, event_handler)

                finally:
                    # Clean up the cancel waiter whether we exited normally,
                    # via _CancelledByEvent, or via app-exit CancelledError.
                    if cancel_waiter and not cancel_waiter.done():
                        cancel_waiter.cancel()

        except _CancelledByEvent:
            _user_cancelled = True

        if _user_cancelled:
            # Don't advance the graph — the outer loop will see cancel_event
            # is set and break before attempting to re-process this node.
            return node

        # Advance the graph — stream() caches _result so node is NOT re-executed.
        return await agent_run.next(node)

    def _handle_streaming_tool_call(
        self,
        part: ToolCallPart,
        state: _RunState,
        event_handler: Callable[[StreamEvent], None],
    ) -> None:
        """Process one ToolCallPart from the streaming response.

        First sighting → emit an early ToolCallEvent (args may be partial).
        Subsequent deltas → throttle via the per-tool stream handler and emit
        a ToolCallUpdateEvent when the handler decides the update is worth showing.
        """
        tid = part.tool_call_id or ""

        if part.tool_name and tid not in state.emitted_early_ids:
            state.emitted_early_ids.add(tid)
            if part.tool_call_id:
                state.call_started[part.tool_call_id] = time.monotonic()
            try:
                early_args: dict | str | None = part.args_as_dict()
            except Exception:
                early_args = None
            event_handler(
                ToolCallEvent(
                    tool_call_id=part.tool_call_id,
                    tool_name=part.tool_name,
                    args=early_args,
                )
            )
        elif (
            tid in state.emitted_early_ids
            and part.tool_name in state.stream_handlers
            and isinstance(part.args, str)
        ):
            partial = try_extract_partial_args(part.args)
            if partial and "path" in partial:
                handler = state.stream_handlers[part.tool_name]
                if handler.should_emit_update(tid, partial):
                    event_handler(
                        ToolCallUpdateEvent(
                            tool_call_id=part.tool_call_id,
                            tool_name=part.tool_name,
                            args=partial,
                        )
                    )

    async def _process_call_tools_node(
        self,
        node: CallToolsNode,
        agent_run,
        state: _RunState,
        event_handler: Callable[[StreamEvent], None],
    ):
        """Finalize tool call display, execute tools, then emit ToolResultEvents."""
        for part in node.model_response.parts:
            if isinstance(part, ToolCallPart):
                self._emit_final_tool_call(part, state, event_handler)

        node = await agent_run.next(node)
        self._emit_tool_results(agent_run.all_messages(), state, event_handler)

        # Yield to the event loop so the TUI can render the result box
        # (background-colour transition) before text streaming starts again.
        await asyncio.sleep(0)
        return node

    def _emit_final_tool_call(
        self,
        part: ToolCallPart,
        state: _RunState,
        event_handler: Callable[[StreamEvent], None],
    ) -> None:
        """Emit a ToolCallEvent or ToolCallUpdateEvent with the completed args."""
        tid = part.tool_call_id
        try:
            full_args: dict | str | None = (
                part.args_as_dict() if hasattr(part, "args_as_dict") else part.args
            )
        except Exception:
            full_args = part.args  # type: ignore[assignment]

        if tid not in state.emitted_early_ids:
            # No early event was fired (e.g. non-streaming path) — emit now.
            if tid:
                state.call_started[tid] = time.monotonic()
            event_handler(
                ToolCallEvent(tool_call_id=tid, tool_name=part.tool_name, args=full_args)
            )
        else:
            event_handler(
                ToolCallUpdateEvent(tool_call_id=tid, tool_name=part.tool_name, args=full_args)
            )

    def _emit_tool_results(
        self,
        messages,
        state: _RunState,
        event_handler: Callable[[StreamEvent], None],
    ) -> None:
        """Scan the most recent request message for ToolReturnParts and emit events."""
        for msg in reversed(messages):
            if msg.kind == "request":
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        content = part.content
                        result_text = content if isinstance(content, str) else str(content)

                        elapsed_s = None
                        tcid = part.tool_call_id
                        if tcid and tcid in state.call_started:
                            elapsed_s = time.monotonic() - state.call_started.pop(tcid)

                        event_handler(
                            ToolResultEvent(
                                tool_call_id=tcid,
                                tool_name=part.tool_name,
                                result=result_text,
                                elapsed_s=elapsed_s,
                                is_error=result_text.lstrip().startswith("Error"),
                            )
                        )
                break
