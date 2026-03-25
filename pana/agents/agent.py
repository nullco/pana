import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic_ai._agent_graph import CallToolsNode, End, ModelRequestNode
from pydantic_ai.agent import Agent as PydanticAgent
from pydantic_ai.messages import TextPart, ToolCallPart, ToolReturnPart

from pana.agents.system_prompt import build_system_prompt
from pana.agents.tools import tool_bash, tool_edit, tool_read, tool_write
from pana.ai.providers.model import Model

logger = logging.getLogger(__name__)


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


# A stream handler receives these events
StreamEvent = ToolCallEvent | ToolCallUpdateEvent | ToolResultEvent | TextEvent


# ---------------------------------------------------------------------------
# Partial-JSON parser for streaming tool_write args
# ---------------------------------------------------------------------------

def _try_extract_partial_write_args(args_str: str) -> dict[str, str] | None:
    """Best-effort extraction of tool_write args from a partial (still-streaming) JSON string.

    The LLM streams args as raw JSON text token by token, so ``args_str`` is
    typically an incomplete JSON object like::

        {"path": "foo.py", "content": "import os\\nimport sys\\n

    We try to extract whatever is already available so the UI can show the
    content preview growing in real time.
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

    # Extract the completed "path" value.  It's a short string that arrives
    # well before the (potentially huge) content, so it's safe to match as a
    # complete JSON string literal.
    path_m = re.search(r'"path"\s*:\s*("(?:[^"\\]|\\.)*?")', args_str)
    if path_m:
        try:
            out["path"] = json.loads(path_m.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # Extract the partial "content" value — everything after its opening quote.
    content_m = re.search(r'"content"\s*:\s*"', args_str)
    if content_m:
        raw = args_str[content_m.end():]
        # Wrap in quotes and try json.loads so we get proper escape decoding
        # (e.g. \\n → actual newline).  This fails if a JSON escape sequence
        # is split across the stream boundary (e.g. trailing bare backslash).
        try:
            out["content"] = json.loads('"' + raw + '"')
        except (json.JSONDecodeError, ValueError):
            # Strip the trailing incomplete escape and try once more.
            trimmed = raw.rstrip("\\")
            try:
                out["content"] = json.loads('"' + trimmed + '"')
            except (json.JSONDecodeError, ValueError):
                # Last resort: manual substitution for the most common escapes.
                out["content"] = (
                    trimmed.replace("\\n", "\n")
                    .replace("\\t", "\t")
                    .replace('\\"', '"')
                    .replace("\\\\", "\\")
                )

    return out if out else None


class Agent:

    def __init__(self, model: Model) -> None:
        self._model = model
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
        # tool_call_ids for which we already fired an early ToolCallEvent
        emitted_early_ids: set[str] = set()
        # per-write-call: how many content lines were in the last update we sent
        write_content_lines: dict[str, int] = {}

        async with self._agent.iter(
            user_input, message_history=self._message_history
        ) as agent_run:
            node = agent_run.next_node
            while not isinstance(node, End):
                if isinstance(node, ModelRequestNode):
                    # Stream responses incrementally so we can detect tool calls
                    # as soon as the tool_name token arrives — well before the
                    # full (potentially large) args JSON is received.
                    last_text = ""
                    async with node.stream(agent_run.ctx) as stream:
                        async for response in stream.stream_responses(debounce_by=0.05):
                            for part in response.parts:
                                if isinstance(part, TextPart):
                                    # Only emit when text has actually grown
                                    if part.content != last_text:
                                        last_text = part.content
                                        event_handler(TextEvent(text=part.content))
                                elif isinstance(part, ToolCallPart):
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
                                        and part.tool_name == "tool_write"
                                        and isinstance(part.args, str)
                                    ):
                                        # ── Subsequent snapshots for tool_write ──
                                        # Stream the growing content into the existing
                                        # box by emitting a ToolCallUpdateEvent whenever
                                        # the content has at least one more line than the
                                        # last update we sent.
                                        partial = _try_extract_partial_write_args(part.args)
                                        if partial and "content" in partial:
                                            content = partial["content"]
                                            cur_lines = content.count("\n") + (
                                                1 if content and not content.endswith("\n") else 0
                                            )
                                            if cur_lines > write_content_lines.get(tid, 0):
                                                write_content_lines[tid] = cur_lines
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
                else:
                    # Unknown node type, just advance
                    node = await agent_run.next(node)

            self._message_history = agent_run.all_messages()
