"""Tests for CodingAgent."""

from unittest.mock import MagicMock, patch

import pytest

from agents import CodingAgent
from agents.coding_agent import AgentInput


class TestCodingAgent:
    def _make_provider(self):
        provider = MagicMock()
        provider.build_model.return_value = MagicMock()
        provider.get_authenticator.return_value = None
        return provider

    def test_clear_history(self):
        """Test that clear_history resets the message history."""
        with patch("agents.base.Agent"):
            agent = CodingAgent(provider=self._make_provider())
            agent._message_history = [{"role": "user", "content": "test"}]

            agent.clear_history()

            assert agent._message_history is None

    @pytest.mark.asyncio
    async def test_stream(self):
        """Test that stream handles agent responses."""
        with patch("agents.base.Agent") as mock_agent_class:
            # Mock the Agent instance and its run_stream method
            mock_agent = MagicMock()
            mock_agent_class.return_value = mock_agent

            # Mock the async context manager and result
            class MockResult:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def stream_output(self):
                    yield "Hello "
                    yield "world"

                def all_messages(self):
                    return [{"role": "assistant", "content": "Hello world"}]

            mock_agent.run_stream.return_value = MockResult()

            agent = CodingAgent(provider=self._make_provider())
            responses = []

            def handler(update):
                responses.append(update)

            await agent.stream("test input", handler)

            assert responses == ["Hello ", "world"]
            assert agent._message_history == [{"role": "assistant", "content": "Hello world"}]


class TestAgentInput:
    def test_agent_input_model(self):
        """Test AgentInput pydantic model."""
        input_data = AgentInput(user_input="Hello, world!")
        assert input_data.user_input == "Hello, world!"
