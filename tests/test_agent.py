"""Tests for CodingAgent."""

from unittest.mock import MagicMock, patch

from agent.agent import AgentInput, CodingAgent


class TestCodingAgent:
    def test_default_model(self, monkeypatch):
        monkeypatch.delenv("AGENT_MODEL", raising=False)

        with patch("agent.agent.Agent.__init__") as mock_init:
            mock_init.return_value = None
            _agent = CodingAgent()  # noqa: F841
            mock_init.assert_called_once()
            call_kwargs = mock_init.call_args
            assert call_kwargs[1]["model"] == "github:gpt-4.1"

    def test_custom_model_from_env(self, monkeypatch):
        monkeypatch.setenv("AGENT_MODEL", "openai:gpt-4")

        with patch("agent.agent.Agent.__init__") as mock_init:
            mock_init.return_value = None
            _agent = CodingAgent()  # noqa: F841
            call_kwargs = mock_init.call_args
            assert call_kwargs[1]["model"] == "openai:gpt-4"

    def test_custom_model_from_arg(self, monkeypatch):
        monkeypatch.delenv("AGENT_MODEL", raising=False)

        with patch("agent.agent.Agent.__init__") as mock_init:
            mock_init.return_value = None
            _agent = CodingAgent(model="anthropic:claude-3")  # noqa: F841
            call_kwargs = mock_init.call_args
            assert call_kwargs[1]["model"] == "anthropic:claude-3"

    def test_clear_history(self):
        with patch("agent.agent.Agent.__init__", return_value=None):
            agent = CodingAgent()
            agent._message_history = [{"role": "user", "content": "test"}]
            
            agent.clear_history()
            
            assert agent._message_history is None


class TestHandleCommand:
    @patch("agent.agent.CopilotAuthenticator")
    def test_login_command(self, mock_auth_class):
        mock_auth = MagicMock()
        mock_auth.start_login.return_value = (True, "[OAuth] Test message")
        mock_auth_class.return_value = mock_auth

        with patch("agent.agent.Agent.__init__", return_value=None):
            agent = CodingAgent()
            agent.copilot_auth = mock_auth

            result = agent.handle_command("/login")

            assert result == "[OAuth] Test message"
            mock_auth.start_login.assert_called_once()

    @patch("agent.agent.CopilotAuthenticator")
    def test_logout_command(self, mock_auth_class):
        mock_auth = MagicMock()
        mock_auth.logout.return_value = "[OAuth] Logged out."
        mock_auth_class.return_value = mock_auth

        with patch("agent.agent.Agent.__init__", return_value=None):
            agent = CodingAgent()
            agent.copilot_auth = mock_auth

            result = agent.handle_command("/logout")

            assert result == "[OAuth] Logged out."
            mock_auth.logout.assert_called_once()

    @patch("agent.agent.CopilotAuthenticator")
    def test_status_command(self, mock_auth_class):
        mock_auth = MagicMock()
        mock_auth.get_status.return_value = "Logged in as: testuser"
        mock_auth_class.return_value = mock_auth

        with patch("agent.agent.Agent.__init__", return_value=None):
            agent = CodingAgent()
            agent.copilot_auth = mock_auth

            result = agent.handle_command("/status")

            assert "[Agent] Logged in as: testuser" in result
            mock_auth.get_status.assert_called_once()

    def test_unknown_command(self):
        with patch("agent.agent.Agent.__init__", return_value=None):
            agent = CodingAgent()
            agent.copilot_auth = MagicMock()

            result = agent.handle_command("/unknown")

            assert "Unknown command" in result


class TestAgentInput:
    def test_agent_input_model(self):
        input_data = AgentInput(user_input="Hello, world!")
        assert input_data.user_input == "Hello, world!"
