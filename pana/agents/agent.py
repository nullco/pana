import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic_ai._agent_graph import CallToolsNode, End, ModelRequestNode
from pydantic_ai.agent import Agent as PydanticAgent
from pydantic_ai.messages import TextPart, ThinkingPart, ToolCallPart, ToolReturnPart
from pydantic_ai.settings import ModelSettings

from pana.agents.system_prompt import build_system_prompt
from pana.agents.tool_streams import build_stream_handlers
from pana.agents.tools import tool_bash, tool_edit, tool_read, tool_write
from pana.ai.providers.model import Model

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thinking levels — maps to openai_reasoning_effort in ModelSettings
# ---------------------------------------------------------------------------

THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh")


# ---------------------------------------------------------------------------
# Events emitted during streaming so the TUI can display tool activity
# ---------------------------------------------------------------------------


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


# A stream handler receives these events
StreamEvent = ToolCallEvent | ToolCallUpdateEvent | ToolResultEvent | TextEvent | ThinkingEvent


# ---------------------------------------------------------------------------
# Partial-JSON parser for streaming tool_write args
# ---------------------------------------------------------------------------

def _try_extract_partial_args(args_str: str) -> dict[str, str] | None:
    """Best-effort extraction of tool args from a partial (still-streaming) JSON string.

    The LLM streams args as raw JSON text token by token, so ``args_str`` is
    typically an incomplete JSON object like::

        {"path": "foo.py", "content": "import os\\nimport sys\\n

    We try to extract whatever is already available so the UI can show
    previews growing in real time.
    """
    if not args_str:
        return None

    # Happy path: JSON is complete — just parse it.
    try:
        result = json.loads(args_str)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    out: dict[str, str] = {}

    # Extract completed JSON string values for known keys.
    # Short values (like "path") arrive well before large ones ("content",
    # "old_text") so we can display them immediately.
    for key in ("path", "content", "old_text", "new_text"):
        m = re.search(rf'"{key}"\s*:\s*("(?:[^"\\]|\\.)*?")', args_str)
        if m:
            try:
                out[key] = json.loads(m.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

    # For "content" specifically, also try to extract a partial (unclosed) value
    # so we can stream the growing file content preview.
    if "content" not in out:
        content_m = re.search(r'"content"\s*:\s*"', args_str)
        if content_m:
            raw = args_str[content_m.end():]
            try:
                out["content"] = json.loads('"' + raw + '"')
            except (json.JSONDecodeError, ValueError):
                trimmed = raw.rstrip("\\")
                try:
                    out["content"] = json.loads('"' + trimmed + '"')
                except (json.JSONDecodeError, ValueError):
                    out["content"] = (
                        trimmed.replace("\\n", "\n")
                        .replace("\\t", "\t")
                        .replace('\\"', '"')
                        .replace("\\\\", "\\")
                    )

    return out if out else None


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
    ) -> None:
        """Run agent with tool call visibility.

        Uses the iter() graph API to surface tool calls and results as they
        happen, interleaved with streamed text output.

        Early ToolCallEvents are fired as soon as the model's tool_name token
        is known (before all args arrive).  A ToolCallUpdateEvent follows once
        args are fully received so the UI can fill in the final display.
        """
        if self._model.provider.should_reauthenticate():
            await self._model.provider.reauthenticate()
            model = await self._model.provider.build_model(self._model.name)
            self.set_model(model)

        call_started: dict[str, float] = {}
        emitted_early_ids: set[str] = set()
        stream_handlers = build_stream_handlers()

        async with self._agent.iter(
            user_input,
            message_history=self._message_history,
            model_settings=self._build_model_settings(),
        ) as agent_run:
            node = agent_run.next_node
            while not isinstance(node, End):
                if isinstance(node, ModelRequestNode):
                    # Stream responses incrementally so we can detect tool calls
                    # as soon as the tool_name token arrives — well before the
                    # full (potentially large) args JSON is received.
                    last_text = ""
                    last_thinking = ""
                    async with node.stream(agent_run.ctx) as stream:
                        async for response in stream.stream_responses(debounce_by=0.05):
                            # The Responses API emits individual parts per
                            # streaming delta, so we must concatenate all parts
                            # of the same type to get the accumulated text.
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
                                    tid = part.tool_call_id or ""
                                    if part.tool_name and tid not in emitted_early_ids:
                                        # ── First detection: fire early ToolCallEvent ──
                                        emitted_early_ids.add(tid)
                                        if part.tool_call_id:
                                            call_started[part.tool_call_id] = time.monotonic()
                                        # Args are likely partial JSON — try to parse,
                                        # fall back to None gracefully.
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
                                        tid in emitted_early_ids
                                        and part.tool_name in stream_handlers
                                        and isinstance(part.args, str)
                                    ):
                                        partial = _try_extract_partial_args(part.args)
                                        if partial and "path" in partial:
                                            handler = stream_handlers[part.tool_name]
                                            if handler.should_emit_update(tid, partial):
                                                event_handler(
                                                    ToolCallUpdateEvent(
                                                        tool_call_id=part.tool_call_id,
                                                        tool_name=part.tool_name,
                                                        args=partial,
                                                    )
                                                )

                    # Advance the graph — run() returns the cached _result set
                    # by stream(), so the node is NOT re-executed.
                    node = await agent_run.next(node)

                elif isinstance(node, CallToolsNode):
                    # Emit final tool call info.  For tools already shown via an
                    # early ToolCallEvent, send a ToolCallUpdateEvent so the UI
                    # can fill in the complete args (e.g. the write content preview).
                    for part in node.model_response.parts:
                        if isinstance(part, ToolCallPart):
                            tid = part.tool_call_id
                            try:
                                full_args: dict | str | None = (
                                    part.args_as_dict()
                                    if hasattr(part, "args_as_dict")
                                    else part.args
                                )
                            except Exception:
                                full_args = part.args  # type: ignore[assignment]

                            if tid not in emitted_early_ids:
                                # Tool call wasn't detected early (no streaming?), emit normally
                                if tid:
                                    call_started[tid] = time.monotonic()
                                event_handler(
                                    ToolCallEvent(
                                        tool_call_id=tid,
                                        tool_name=part.tool_name,
                                        args=full_args,
                                    )
                                )
                            else:
                                # Update the existing box with the final args
                                event_handler(
                                    ToolCallUpdateEvent(
                                        tool_call_id=tid,
                                        tool_name=part.tool_name,
                                        args=full_args,
                                    )
                                )

                    # Execute tools (advances the graph)
                    node = await agent_run.next(node)

                    # Get results from the last request message
                    messages = agent_run.all_messages()
                    for msg in reversed(messages):
                        if msg.kind == "request":
                            for part in msg.parts:
                                if isinstance(part, ToolReturnPart):
                                    content = part.content
                                    result_text = content if isinstance(content, str) else str(content)

                                    elapsed_s = None
                                    tcid = part.tool_call_id
                                    if tcid and tcid in call_started:
                                        elapsed_s = time.monotonic() - call_started.pop(tcid)

                                    is_error = result_text.lstrip().startswith("Error")

                                    event_handler(
                                        ToolResultEvent(
                                            tool_call_id=tcid,
                                            tool_name=part.tool_name,
                                            result=result_text,
                                            elapsed_s=elapsed_s,
                                            is_error=is_error,
                                        )
                                    )
                            break

                    # Yield to the event loop so the TUI can render the
                    # result (bg color transition) before text streaming
                    # starts on the next ModelRequestNode.
                    await asyncio.sleep(0)
                else:
                    # Unknown node type, just advance
                    node = await agent_run.next(node)

            self._message_history = agent_run.all_messages()
