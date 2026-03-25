import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic_ai._agent_graph import CallToolsNode, End, ModelRequestNode
from pydantic_ai.agent import Agent as PydanticAgent
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.result import FinalResult

from pana.agents.context import collect_agents_md
from pana.agents.tools import tool_bash, tool_edit, tool_read, tool_write
from pana.ai.providers.model import Model

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Events emitted during streaming so the TUI can display tool activity
# ---------------------------------------------------------------------------


@dataclass
class ToolCallEvent:
    """Fired when the model invokes a tool."""

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
StreamEvent = ToolCallEvent | ToolResultEvent | TextEvent


class Agent:

    def __init__(self, model: Model) -> None:
        self._model = model
        self._system_prompt = collect_agents_md()
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
        self._system_prompt = collect_agents_md()
        self._agent = self._build_agent()

    async def stream(
        self,
        user_input: str,
        event_handler: Callable[[StreamEvent], None],
    ) -> None:
        """Run agent with tool call visibility.

        Uses the iter() graph API to surface tool calls and results as they
        happen, interleaved with streamed text output.
        """
        if self._model.provider.should_reauthenticate():
            await self._model.provider.reauthenticate()
            model = await self._model.provider.build_model(self._model.name)
            self.set_model(model)

        call_started: dict[str, float] = {}

        async with self._agent.iter(
            user_input, message_history=self._message_history
        ) as agent_run:
            node = agent_run.next_node
            while not isinstance(node, End):
                if isinstance(node, ModelRequestNode):
                    # Stream text output from the model
                    async with node.stream(agent_run.ctx) as stream:
                        async for text in stream.stream_output(debounce_by=0.05):
                            event_handler(TextEvent(text=text))
                    # Advance the graph — run() returns the cached _result
                    # set by stream(), so the node is NOT re-executed.
                    node = await agent_run.next(node)
                elif isinstance(node, CallToolsNode):
                    # Emit tool call events from the model response
                    for part in node.model_response.parts:
                        if isinstance(part, ToolCallPart):
                            tool_call_id = part.tool_call_id
                            if tool_call_id:
                                call_started[tool_call_id] = time.monotonic()
                            event_handler(
                                ToolCallEvent(
                                    tool_call_id=tool_call_id,
                                    tool_name=part.tool_name,
                                    args=part.args_as_dict() if hasattr(part, "args_as_dict") else part.args,
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
