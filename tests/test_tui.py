"""Smoke tests for the TUI application."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tui import CodingAgentApp, MessageOutput, UserInput


@pytest.fixture
def mock_app_config():
    """Create a mock AppConfig."""
    with patch("app.tui.app.AppConfig") as mock_class:
        mock_config = MagicMock()
        mock_agent = MagicMock()
        mock_auth = MagicMock()
        
        mock_config.agent = mock_agent
        mock_config.get_authenticator = MagicMock(return_value=mock_auth)
        mock_config.get_model_manager = MagicMock(return_value=None)
        
        mock_agent.clear_history = MagicMock()
        mock_auth.cancel = MagicMock()

        async def mock_stream(user_input, handler):
            handler("Test response from agent")

        mock_agent.stream = AsyncMock(side_effect=mock_stream)
        mock_class.return_value = mock_config
        yield mock_config


class TestCodingAgentApp:
    @pytest.mark.asyncio
    async def test_app_starts(self, mock_app_config):
        """Test that the app starts and has expected widgets."""
        app = CodingAgentApp()
        async with app.run_test() as _pilot:  # noqa: F841
            assert app.query_one("#user_input", UserInput) is not None
            assert app.query_one("#chat-container") is not None
            assert app.query_one("#header") is not None
            assert app.query_one("#footer") is not None

    @pytest.mark.asyncio
    async def test_chat_message(self, mock_app_config):
        """Test sending a chat message."""
        app = CodingAgentApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user_input", UserInput)
            input_widget.text = "Hello agent"
            input_widget.post_message(UserInput.Submit("Hello agent"))
            await pilot.pause()

            app.app_config.agent.stream.assert_called_once()

            messages = app.query(MessageOutput)
            assert len(messages) >= 2

    @pytest.mark.asyncio
    async def test_empty_input_ignored(self, mock_app_config):
        """Test that empty input is ignored."""
        app = CodingAgentApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user_input", UserInput)
            input_widget.text = "   "
            input_widget.post_message(UserInput.Submit("   "))
            await pilot.pause()

            app.app_config.agent.stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_clear_command(self, mock_app_config):
        """Test /clear command clears history."""
        app = CodingAgentApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user_input", UserInput)
            input_widget.text = "/clear"
            input_widget.post_message(UserInput.Submit("/clear"))
            await pilot.pause()

            app.app_config.agent.clear_history.assert_called_once()


class TestMessageOutput:
    @pytest.mark.asyncio
    async def test_message_output_renders_markdown(self, mock_app_config):
        """Test MessageOutput stores and can update text."""
        app = CodingAgentApp()
        async with app.run_test():
            msg = MessageOutput(text="**bold** text")
            assert msg.text == "**bold** text"

            msg.text = "# Header"
            assert msg.text == "# Header"


class TestUserInput:
    @pytest.mark.asyncio
    async def test_user_input_is_textarea(self, mock_app_config):
        """Test UserInput is a TextArea."""
        app = CodingAgentApp()
        async with app.run_test():
            from textual.widgets import TextArea

            input_widget = app.query_one("#user_input", UserInput)
            assert isinstance(input_widget, TextArea)
