"""Base agent for LLM interactions."""

from __future__ import annotations

import logging

from pydantic_ai.agent import Agent

from ai.types import Provider

logger = logging.getLogger(__name__)


class BaseAgent:
    """Base agent for LLM interactions through AI providers.

    This is a lightweight wrapper around pydantic_ai Agent that handles
    provider access and message history.
    """

    def __init__(self, provider: Provider, model_name: str | None = None):
        """Initialize the agent with an AI provider.

        Args:
            provider: Provider instance (e.g., CopilotProvider, OpenAIProvider).
            model_name: Name/ID of the model to use. If None, uses provider default.
        """
        self.provider = provider
        self.model_name = model_name
        self._message_history = None
        self._agent = None
        self._model = None

    def _build_model(self):
        self._model = self.provider.build_model(self.model_name)
        return self._model

    def _refresh_if_needed(self):
        auth = self.provider.get_authenticator()
        try:
            if auth and auth.refresh_token():
                logger.debug("auth.refresh_token() returned True — rebuilding model")
                return self._build_model()
        except Exception:
            logger.debug("auth.refresh_token() failed, ignoring")
        if not self._model:
            return self._build_model()
        return self._model

    def _get_agent(self) -> Agent:
        """Get or create the pydantic_ai Agent instance."""
        if self._agent is None:
            model = self._refresh_if_needed()
            self._agent = Agent(model=model)
        else:
            model = self._refresh_if_needed()
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
        self._model = None

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
