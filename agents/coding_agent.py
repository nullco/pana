"""Coding-specific agent."""

from __future__ import annotations

from pydantic import BaseModel

from .base import BaseAgent
from ai.types import Provider


class AgentInput(BaseModel):
    """Input model for the coding agent."""

    user_input: str


class CodingAgent(BaseAgent):
    """Agent specialized for coding tasks."""

    Input = AgentInput

    def __init__(self, provider: Provider, model_name: str | None = None, **kwargs):
        """Initialize the coding agent.

        Args:
            provider: Provider instance (e.g., CopilotProvider, OpenAIProvider).
            model_name: Name/ID of the model to use. If None, uses provider default.
        """
        super().__init__(provider=provider, model_name=model_name)
        self._kwargs = kwargs

    async def chat(self, user_input: str) -> None:
        """Send a message and handle the response.

        This is an alias for stream() for more intuitive naming.

        Args:
            user_input: The user's message.
            stream_handler: Callback for streaming updates.
        """
        # This method exists for semantic clarity; actual streaming
        # should use the stream() method with a handler.
        pass
