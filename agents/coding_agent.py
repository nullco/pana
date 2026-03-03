"""Coding-specific agent."""

from __future__ import annotations

from pydantic import BaseModel

from .base import BaseAgent


class AgentInput(BaseModel):
    """Input model for the coding agent."""

    user_input: str


class CodingAgent(BaseAgent):
    """Agent specialized for coding tasks."""

    Input = AgentInput

    def __init__(self, provider_name: str | None = None, **kwargs):
        """Initialize the coding agent.
        
        Args:
            provider_name: Name of the provider (e.g., 'copilot', 'openai').
        """
        super().__init__(provider_name=provider_name)
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
