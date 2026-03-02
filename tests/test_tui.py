"""Smoke tests for the TUI application."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import Input

from agent.__main__ import CodingAgentApp, MessageOutput


@pytest.fixture
def mock_agent():
    """Create a mock CodingAgent."""
    with patch("agent.__main__.CodingAgent") as mock_class:
        mock_instance = MagicMock()
        mock_instance.copilot_auth = MagicMock()
        mock_instance.copilot_auth.cancel = MagicMock()
        mock_instance.clear_history = MagicMock()
        mock_instance.handle_command = MagicMock(return_value="[Agent] Command result")

        async def mock_stream(input_data, handler):
            handler("Test response from agent")

        mock_instance.stream = AsyncMock(side_effect=mock_stream)
        mock_class.return_value = mock_instance
        yield mock_instance


class TestCodingAgentApp:
    @pytest.mark.asyncio
    async def test_app_starts(self, mock_agent):
        """Test that the app starts and has expected widgets."""
        app = CodingAgentApp()
        async with app.run_test() as _pilot:  # noqa: F841
            assert app.query_one("#user_input", Input) is not None
            assert app.query_one("#chat-container") is not None
            assert app.query_one("#header") is not None
            assert app.query_one("#footer") is not None

    @pytest.mark.asyncio
    async def test_help_command(self, mock_agent):
        """Test /help command shows help text."""
        app = CodingAgentApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user_input", Input)
            input_widget.value = "/help"
            await input_widget.action_submit()
            await pilot.pause()

            messages = app.query(MessageOutput)
            assert len(messages) > 0

            help_shown = any(
                "/login" in msg.text and "/logout" in msg.text for msg in messages
            )
            assert help_shown

    @pytest.mark.asyncio
    async def test_clear_command(self, mock_agent):
        """Test /clear command clears history."""
        app = CodingAgentApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user_input", Input)
            input_widget.value = "/clear"
            await input_widget.action_submit()
            await pilot.pause()

            mock_agent.clear_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_command_shows_help(self, mock_agent):
        """Test unknown command shows help."""
        app = CodingAgentApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user_input", Input)
            input_widget.value = "/unknowncommand"
            await input_widget.action_submit()
            await pilot.pause()

            messages = app.query(MessageOutput)
            unknown_msg = [m for m in messages if "Unknown command" in m.text]
            assert len(unknown_msg) > 0

    @pytest.mark.asyncio
    async def test_chat_message(self, mock_agent):
        """Test sending a chat message."""
        app = CodingAgentApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user_input", Input)
            input_widget.value = "Hello agent"
            await input_widget.action_submit()
            await pilot.pause()

            mock_agent.stream.assert_called_once()

            messages = app.query(MessageOutput)
            assert len(messages) >= 2

    @pytest.mark.asyncio
    async def test_empty_input_ignored(self, mock_agent):
        """Test that empty input is ignored."""
        app = CodingAgentApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user_input", Input)
            input_widget.value = "   "
            await input_widget.action_submit()
            await pilot.pause()

            mock_agent.stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_status_command(self, mock_agent):
        """Test /status command."""
        mock_agent.handle_command.return_value = "[Agent] Not logged in"

        app = CodingAgentApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user_input", Input)
            input_widget.value = "/status"
            await input_widget.action_submit()
            await pilot.pause()

            mock_agent.handle_command.assert_called_with("/status")


class TestMessageOutput:
    @pytest.mark.asyncio
    async def test_message_output_readonly(self, mock_agent):
        """Test MessageOutput is read-only."""
        app = CodingAgentApp()
        async with app.run_test():
            msg = MessageOutput(text="Test message")
            assert msg.read_only is True
            assert msg.language == "markdown"


class TestCommandAutoComplete:
    @pytest.mark.asyncio
    async def test_autocomplete_exists(self, mock_agent):
        """Test that autocomplete widget is present."""
        from agent.__main__ import CommandAutoComplete

        app = CodingAgentApp()
        async with app.run_test() as _pilot:  # noqa: F841
            autocomplete = app.query_one(CommandAutoComplete)
            assert autocomplete is not None

    @pytest.mark.asyncio
    async def test_autocomplete_shows_commands_on_slash(self, mock_agent):
        """Test autocomplete returns commands when input starts with /."""
        from agent.__main__ import CommandAutoComplete
        from textual_autocomplete._autocomplete import TargetState

        autocomplete = CommandAutoComplete(target=MagicMock(), candidates=None)

        state = MagicMock(spec=TargetState)
        state.text = "/he"

        candidates = autocomplete.get_candidates(state)
        assert len(candidates) > 0
        assert any("/help" in str(c.main) for c in candidates)

    @pytest.mark.asyncio
    async def test_autocomplete_hidden_without_slash(self, mock_agent):
        """Test autocomplete returns no candidates for regular text."""
        from agent.__main__ import CommandAutoComplete
        from textual_autocomplete._autocomplete import TargetState

        autocomplete = CommandAutoComplete(target=MagicMock(), candidates=None)

        state = MagicMock(spec=TargetState)
        state.text = "hello"

        candidates = autocomplete.get_candidates(state)
        assert len(candidates) == 0
