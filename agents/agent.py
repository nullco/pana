import logging
from collections.abc import Callable
from dataclasses import dataclass

from pydantic_ai._agent_graph import CallToolsNode, End, ModelRequestNode
from pydantic_ai.agent import Agent as PydanticAgent
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.result import FinalResult

from agents.context import collect_agents_md
from agents.tools import tool_bash, tool_edit, tool_read, tool_write
from ai.providers.model import Model

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Events emitted during streaming so the TUI can display tool activity
# ---------------------------------------------------------------------------


@dataclass
class ToolCallEvent:
    """Fired when the model invokes a tool."""

    tool_name: str
    args: dict | str | None


@dataclass
class ToolResultEvent:
    """Fired when a tool returns its result."""

    tool_name: str
    result: str


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
                            event_handler(
                                ToolCallEvent(
                                    tool_name=part.tool_name,
                                    args=part.args_as_dict() if hasattr(part, "args_as_dict") else part.args,
                                )
                            )

                    # Execute tools (advances the graph)
                    node = await agent_run.next(node)

                    # Emit tool result events from the messages
                    if hasattr(node, "user_prompt") and node.user_prompt:
                        # After tool execution, the next node's user_prompt
                        # may not have results. Check tool_call_results instead.
                        pass

                    # Get results from the last request message
                    messages = agent_run.all_messages()
                    for msg in reversed(messages):
                        if msg.kind == "request":
                            for part in msg.parts:
                                if isinstance(part, ToolReturnPart):
                                    content = part.content
                                    if isinstance(content, str):
                                        result_text = content
                                    else:
                                        result_text = str(content)
                                    event_handler(
                                        ToolResultEvent(
                                            tool_name=part.tool_name,
                                            result=result_text,
                                        )
                                    )
                            break
                else:
                    # Unknown node type, just advance
                    node = await agent_run.next(node)

            self._message_history = agent_run.all_messages()
