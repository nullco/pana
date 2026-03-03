"""Tests for CodingAgent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents import CodingAgent
from agents.coding_agent import AgentInput


class TestCodingAgent:
    def test_clear_history(self):
        """Test that clear_history resets the message history."""
        with patch("agents.base.AIManager"):
            with patch("agents.base.Agent"):
                agent = CodingAgent()
                agent._message_history = [{"role": "user", "content": "test"}]

                agent.clear_history()

                assert agent._message_history is None

    @pytest.mark.asyncio
    async def test_stream(self):
        """Test that stream handles agent responses."""
        with patch("agents.base.AIManager") as mock_manager:
            with patch("agents.base.Agent") as mock_agent_class:
                mock_manager_instance = mock_manager.return_value
                mock_manager_instance.refresh_if_needed.return_value = MagicMock()
                
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

                agent = CodingAgent()
                responses = []

                def handler(update):
                    responses.append(update)

                await agent.stream("test input", handler)

                assert responses == ["Hello ", "world"]
                assert agent._message_history == [{"role": "assistant", "content": "Hello world"}]

    def test_get_authenticator(self):
        """Test that get_authenticator returns the provider's authenticator."""
        with patch("agents.base.AIManager") as mock_manager:
            with patch("agents.base.Agent"):
                mock_auth = MagicMock()
                mock_manager_instance = mock_manager.return_value
                mock_manager_instance.get_authenticator.return_value = mock_auth

                agent = CodingAgent()
                result = agent.get_authenticator()

                assert result == mock_auth

    def test_get_model_manager(self):
        """Test that get_model_manager returns the provider's model manager."""
        with patch("agents.base.AIManager") as mock_manager:
            with patch("agents.base.Agent"):
                mock_mm = MagicMock()
                mock_manager_instance = mock_manager.return_value
                mock_manager_instance.get_model_manager.return_value = mock_mm

                agent = CodingAgent()
                result = agent.get_model_manager()

                assert result == mock_mm


class TestAgentInput:
    def test_agent_input_model(self):
        """Test AgentInput pydantic model."""
        input_data = AgentInput(user_input="Hello, world!")
        assert input_data.user_input == "Hello, world!"
