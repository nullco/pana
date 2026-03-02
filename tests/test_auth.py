"""Tests for CopilotAuthenticator."""

import os
from unittest.mock import patch

from agent.auth import CopilotAuthenticator
from agent.copilot_oauth import CopilotCredentials, DeviceCodeResponse, OAuthError


class TestCopilotAuthenticator:
    def test_initial_state(self):
        auth = CopilotAuthenticator()
        assert auth.github_token is None
        assert auth.copilot_token is None
        assert not auth.is_logged_in()

    def test_get_status_not_logged_in(self):
        auth = CopilotAuthenticator()
        assert auth.get_status() == "Not logged in"

    @patch("agent.auth.copilot_oauth.get_github_username")
    def test_get_status_logged_in(self, mock_get_username):
        mock_get_username.return_value = "testuser"
        auth = CopilotAuthenticator()
        auth.github_token = "test_token"

        assert auth.get_status() == "Logged in as: testuser"

    @patch("agent.auth.copilot_oauth.get_github_username")
    def test_get_status_logged_in_no_username(self, mock_get_username):
        mock_get_username.return_value = None
        auth = CopilotAuthenticator()
        auth.github_token = "test_token"

        assert auth.get_status() == "Logged in"


class TestStartLogin:
    @patch("agent.auth.copilot_oauth.start_device_flow")
    def test_success(self, mock_start_flow):
        mock_start_flow.return_value = DeviceCodeResponse(
            device_code="dc123",
            user_code="ABCD-1234",
            verification_uri="https://github.com/login/device",
            interval=5,
        )

        auth = CopilotAuthenticator()
        success, msg = auth.start_login()

        assert success is True
        assert "ABCD-1234" in msg
        assert "https://github.com/login/device" in msg
        assert auth._device_code == "dc123"
        assert auth._poll_interval == 5

    @patch("agent.auth.copilot_oauth.start_device_flow")
    def test_error(self, mock_start_flow):
        mock_start_flow.side_effect = OAuthError("Test error")

        auth = CopilotAuthenticator()
        success, msg = auth.start_login()

        assert success is False
        assert "[OAuth] Error" in msg
        assert "Test error" in msg


class TestPollForToken:
    def test_not_started(self):
        auth = CopilotAuthenticator()
        success, msg = auth.poll_for_token()

        assert success is False
        assert "Login not started" in msg

    @patch("agent.auth.copilot_oauth.get_github_username")
    @patch("agent.auth.copilot_oauth.enable_all_models")
    @patch("agent.auth.copilot_oauth.exchange_for_copilot_token")
    @patch("agent.auth.copilot_oauth.poll_for_token")
    def test_success(
        self, mock_poll, mock_exchange, mock_enable, mock_username
    ):
        mock_poll.return_value = "gho_github_token"
        mock_exchange.return_value = CopilotCredentials(
            github_token="gho_github_token",
            copilot_token="copilot_token_123",
            expires_ms=1700000000000,
        )
        mock_username.return_value = "testuser"

        auth = CopilotAuthenticator()
        auth._device_code = "dc123"

        success, msg = auth.poll_for_token()

        assert success is True
        assert "testuser" in msg
        assert auth.github_token == "gho_github_token"
        assert auth.copilot_token == "copilot_token_123"
        assert os.environ.get("GITHUB_API_KEY") == "gho_github_token"
        assert os.environ.get("COPILOT_API_KEY") == "copilot_token_123"

        del os.environ["GITHUB_API_KEY"]
        del os.environ["COPILOT_API_KEY"]

    @patch("agent.auth.copilot_oauth.poll_for_token")
    def test_cancelled(self, mock_poll):
        mock_poll.side_effect = OAuthError("cancelled")

        auth = CopilotAuthenticator()
        auth._device_code = "dc123"

        success, msg = auth.poll_for_token()

        assert success is False
        assert "Cancelled" in msg

    @patch("agent.auth.copilot_oauth.poll_for_token")
    def test_error(self, mock_poll):
        mock_poll.side_effect = OAuthError("Some error")

        auth = CopilotAuthenticator()
        auth._device_code = "dc123"

        success, msg = auth.poll_for_token()

        assert success is False
        assert "[OAuth] Error" in msg
        assert "Some error" in msg


class TestLogout:
    def test_clears_tokens(self):
        auth = CopilotAuthenticator()
        auth.github_token = "test"
        auth.copilot_token = "test2"
        auth._device_code = "dc"

        os.environ["GITHUB_API_KEY"] = "test"
        os.environ["COPILOT_API_KEY"] = "test2"

        msg = auth.logout()

        assert "[OAuth] Logged out" in msg
        assert auth.github_token is None
        assert auth.copilot_token is None
        assert auth._device_code is None
        assert "GITHUB_API_KEY" not in os.environ
        assert "COPILOT_API_KEY" not in os.environ


class TestSaveTokens:
    def test_saves_tokens_with_permissions(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AGENT_PERSIST_TOKENS", "true")

        auth = CopilotAuthenticator()
        auth.github_token = "gh_token"
        auth.copilot_token = "cp_token"

        auth._save_tokens()

        env_path = tmp_path / ".env"
        assert env_path.exists()

        content = env_path.read_text()
        assert "GITHUB_API_KEY=gh_token" in content
        assert "COPILOT_API_KEY=cp_token" in content

        import stat
        mode = env_path.stat().st_mode
        assert mode & stat.S_IRUSR
        assert mode & stat.S_IWUSR
        assert not (mode & stat.S_IRGRP)
        assert not (mode & stat.S_IROTH)

    def test_preserves_existing_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        env_path = tmp_path / ".env"
        env_path.write_text("EXISTING_VAR=value\n")

        auth = CopilotAuthenticator()
        auth.github_token = "gh_token"

        auth._save_tokens()

        content = env_path.read_text()
        assert "EXISTING_VAR=value" in content
        assert "GITHUB_API_KEY=gh_token" in content


class TestRemoveTokensFromEnvFile:
    def test_removes_tokens(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        env_path = tmp_path / ".env"
        env_path.write_text(
            "EXISTING_VAR=value\n"
            "GITHUB_API_KEY=old_token\n"
            "COPILOT_API_KEY=old_copilot\n"
            "ANOTHER_VAR=other\n"
        )

        auth = CopilotAuthenticator()
        auth._remove_tokens_from_env_file()

        content = env_path.read_text()
        assert "EXISTING_VAR=value" in content
        assert "ANOTHER_VAR=other" in content
        assert "GITHUB_API_KEY" not in content
        assert "COPILOT_API_KEY" not in content

    def test_handles_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        auth = CopilotAuthenticator()
        auth._remove_tokens_from_env_file()
