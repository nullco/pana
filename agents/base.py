"""Base agent for LLM interactions."""

from __future__ import annotations

from pydantic_ai.agent import Agent

from ai.manager import AIManager


class BaseAgent:
    """Base agent for LLM interactions through AI providers.
    
    This is a lightweight wrapper around pydantic_ai Agent that handles
    provider management and message history.
    """

    def __init__(self, provider_name: str | None = None):
        """Initialize the agent with an AI provider.
        
        Args:
            provider_name: Name of the provider (e.g., 'copilot', 'openai').
                          If None, uses default provider.
        """
        self.ai_manager = AIManager(provider_name)
        self._message_history = None
        self._agent = None

    def _get_agent(self) -> Agent:
        """Get or create the pydantic_ai Agent instance."""
        if self._agent is None:
            model = self.ai_manager.refresh_if_needed()
            self._agent = Agent(model=model)
        else:
            # Refresh model if needed and update agent
            model = self.ai_manager.refresh_if_needed()
            self._agent.model = model
        return self._agent

    def clear_history(self) -> None:
        """Clear the message history."""
        self._message_history = None

    def refresh_agent(self) -> None:
        """Force refresh of the agent's model.
        
        Call this after authentication tokens are updated.
        """
        self._agent = None

    async def stream(self, user_input: str, stream_handler) -> None:
        """Stream responses from the agent.
        
        Args:
            user_input: User's input message.
            stream_handler: Callback function to handle streamed updates.
        """
        agent = self._get_agent()
        async with agent.run_stream(
            user_input, message_history=self._message_history
        ) as result:
            async for update in result.stream_output():
                stream_handler(update)
            self._message_history = result.all_messages()

    def get_authenticator(self):
        """Get the provider's authenticator (if available)."""
        return self.ai_manager.get_authenticator()

    def get_model_manager(self):
        """Get the provider's model manager (if available)."""
        return self.ai_manager.get_model_manager()

