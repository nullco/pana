"""Tests for copilot_oauth module."""

import threading

import pytest

from agent.copilot_oauth import (
    CopilotCredentials,
    DeviceCodeResponse,
    OAuthError,
    exchange_for_copilot_token,
    get_copilot_base_url,
    get_github_username,
    poll_for_token,
    start_device_flow,
)


class TestStartDeviceFlow:
    def test_success(self, requests_mock):
        requests_mock.post(
            "https://github.com/login/device/code",
            json={
                "device_code": "test_device_code",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "interval": 5,
            },
        )

        result = start_device_flow()

        assert isinstance(result, DeviceCodeResponse)
        assert result.device_code == "test_device_code"
        assert result.user_code == "ABCD-1234"
        assert result.verification_uri == "https://github.com/login/device"
        assert result.interval == 5

    def test_uses_verification_uri_complete(self, requests_mock):
        requests_mock.post(
            "https://github.com/login/device/code",
            json={
                "device_code": "test",
                "user_code": "TEST",
                "verification_uri": "https://github.com/login/device",
                "verification_uri_complete": "https://github.com/login/device?user_code=TEST",
                "interval": 5,
            },
        )

        result = start_device_flow()
        assert result.verification_uri == "https://github.com/login/device?user_code=TEST"

    def test_404_error(self, requests_mock):
        requests_mock.post(
            "https://github.com/login/device/code",
            status_code=404,
        )

        with pytest.raises(OAuthError) as exc_info:
            start_device_flow()

        assert "404" in str(exc_info.value)
        assert "client_id" in str(exc_info.value)

    def test_non_200_error(self, requests_mock):
        requests_mock.post(
            "https://github.com/login/device/code",
            status_code=500,
            text="Internal Server Error",
        )

        with pytest.raises(OAuthError) as exc_info:
            start_device_flow()

        assert "500" in str(exc_info.value)

    def test_invalid_json(self, requests_mock):
        requests_mock.post(
            "https://github.com/login/device/code",
            text="not json",
            status_code=200,
        )

        with pytest.raises(OAuthError) as exc_info:
            start_device_flow()

        assert "parse" in str(exc_info.value).lower()

    def test_missing_device_code(self, requests_mock):
        requests_mock.post(
            "https://github.com/login/device/code",
            json={"user_code": "TEST"},
        )

        with pytest.raises(OAuthError) as exc_info:
            start_device_flow()

        assert "Invalid" in str(exc_info.value)

    def test_network_error(self, requests_mock):
        import requests

        requests_mock.post(
            "https://github.com/login/device/code",
            exc=requests.exceptions.ConnectionError("Network error"),
        )

        with pytest.raises(OAuthError) as exc_info:
            start_device_flow()

        assert "failed" in str(exc_info.value).lower()


class TestPollForToken:
    def test_success_immediate(self, requests_mock):
        requests_mock.post(
            "https://github.com/login/oauth/access_token",
            json={"access_token": "gho_test_token"},
        )

        result = poll_for_token("test_device_code", interval=0)

        assert result == "gho_test_token"

    def test_pending_then_success(self, requests_mock):
        responses = [
            {"json": {"error": "authorization_pending"}},
            {"json": {"error": "authorization_pending"}},
            {"json": {"access_token": "gho_test_token"}},
        ]
        requests_mock.post(
            "https://github.com/login/oauth/access_token",
            responses,
        )

        result = poll_for_token("test_device_code", interval=0)

        assert result == "gho_test_token"

    def test_slow_down_increases_interval(self, requests_mock):
        responses = [
            {"json": {"error": "slow_down"}},
            {"json": {"access_token": "gho_test_token"}},
        ]
        requests_mock.post(
            "https://github.com/login/oauth/access_token",
            responses,
        )

        result = poll_for_token("test_device_code", interval=0)
        assert result == "gho_test_token"

    def test_error_response(self, requests_mock):
        requests_mock.post(
            "https://github.com/login/oauth/access_token",
            json={"error": "access_denied", "error_description": "User denied access"},
        )

        with pytest.raises(OAuthError) as exc_info:
            poll_for_token("test_device_code", interval=0)

        assert "User denied access" in str(exc_info.value)

    def test_missing_access_token(self, requests_mock):
        requests_mock.post(
            "https://github.com/login/oauth/access_token",
            json={"some_other_field": "value"},
        )

        with pytest.raises(OAuthError) as exc_info:
            poll_for_token("test_device_code", interval=0)

        assert "No access token" in str(exc_info.value)

    def test_cancel_event(self, requests_mock):
        cancel_event = threading.Event()
        cancel_event.set()

        with pytest.raises(OAuthError) as exc_info:
            poll_for_token("test_device_code", cancel_event=cancel_event, interval=0)

        assert str(exc_info.value) == "cancelled"

    def test_timeout(self, requests_mock):
        requests_mock.post(
            "https://github.com/login/oauth/access_token",
            json={"error": "authorization_pending"},
        )

        with pytest.raises(OAuthError) as exc_info:
            poll_for_token("test_device_code", interval=0, timeout_seconds=0)

        assert "Timed out" in str(exc_info.value)

    def test_network_error(self, requests_mock):
        import requests

        requests_mock.post(
            "https://github.com/login/oauth/access_token",
            exc=requests.exceptions.ConnectionError("Network error"),
        )

        with pytest.raises(OAuthError) as exc_info:
            poll_for_token("test_device_code", interval=0)

        assert "failed" in str(exc_info.value).lower()


class TestExchangeForCopilotToken:
    def test_success(self, requests_mock):
        requests_mock.get(
            "https://api.github.com/copilot_internal/v2/token",
            json={"token": "copilot_token_123", "expires_at": 1700000000.0},
        )

        result = exchange_for_copilot_token("github_token")

        assert isinstance(result, CopilotCredentials)
        assert result.github_token == "github_token"
        assert result.copilot_token == "copilot_token_123"
        assert result.expires_ms is not None

    def test_non_200_returns_none_copilot_token(self, requests_mock):
        requests_mock.get(
            "https://api.github.com/copilot_internal/v2/token",
            status_code=401,
        )

        result = exchange_for_copilot_token("github_token")

        assert result.github_token == "github_token"
        assert result.copilot_token is None

    def test_invalid_json_returns_none(self, requests_mock):
        requests_mock.get(
            "https://api.github.com/copilot_internal/v2/token",
            text="not json",
        )

        result = exchange_for_copilot_token("github_token")

        assert result.copilot_token is None

    def test_missing_token_field(self, requests_mock):
        requests_mock.get(
            "https://api.github.com/copilot_internal/v2/token",
            json={"other": "data"},
        )

        result = exchange_for_copilot_token("github_token")

        assert result.copilot_token is None

    def test_network_error(self, requests_mock):
        import requests

        requests_mock.get(
            "https://api.github.com/copilot_internal/v2/token",
            exc=requests.exceptions.ConnectionError("Network error"),
        )

        result = exchange_for_copilot_token("github_token")

        assert result.copilot_token is None


class TestGetGithubUsername:
    def test_success(self, requests_mock):
        requests_mock.get(
            "https://api.github.com/user",
            json={"login": "testuser"},
        )

        result = get_github_username("token")

        assert result == "testuser"

    def test_non_200_returns_none(self, requests_mock):
        requests_mock.get(
            "https://api.github.com/user",
            status_code=401,
        )

        result = get_github_username("token")

        assert result is None

    def test_network_error_returns_none(self, requests_mock):
        import requests

        requests_mock.get(
            "https://api.github.com/user",
            exc=requests.exceptions.ConnectionError("Network error"),
        )

        result = get_github_username("token")

        assert result is None


class TestGetCopilotBaseUrl:
    def test_default_url(self):
        result = get_copilot_base_url(None)
        assert result == "https://api.individual.githubcopilot.com"

    def test_extracts_proxy_endpoint(self):
        token = "tid=abc;exp=123;proxy-ep=proxy.example.com;other=stuff"
        result = get_copilot_base_url(token)
        assert result == "https://api.example.com"

    def test_no_proxy_in_token(self):
        token = "tid=abc;exp=123"
        result = get_copilot_base_url(token)
        assert result == "https://api.individual.githubcopilot.com"
