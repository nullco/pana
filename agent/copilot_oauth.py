"""GitHub Copilot OAuth helpers (device flow and token exchange)."""

from __future__ import annotations

import base64
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import requests

if TYPE_CHECKING:
    import threading

logger = logging.getLogger(__name__)

COPILOT_HEADERS = {
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
}

CLIENT_ID = base64.b64decode("SXYxLmI1MDdhMDhjODdlY2ZlOTg=").decode()
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
DEFAULT_SCOPE = "read:user copilot"

DEFAULT_POLL_TIMEOUT_SECONDS = 600  # 10 minutes


@dataclass
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int


@dataclass
class CopilotCredentials:
    github_token: str
    copilot_token: str | None
    expires_ms: int | None


class OAuthError(Exception):
    """OAuth-related error."""


def start_device_flow(
    client_id: str = CLIENT_ID,
    scope: str = DEFAULT_SCOPE,
) -> DeviceCodeResponse:
    """Start the GitHub device OAuth flow."""
    headers = {"Accept": "application/json", **COPILOT_HEADERS}
    data = {"client_id": client_id, "scope": scope}

    try:
        resp = requests.post(DEVICE_CODE_URL, data=data, headers=headers, timeout=10)
    except requests.RequestException as e:
        raise OAuthError(f"Device code request failed: {e}") from e

    if resp.status_code == 404:
        raise OAuthError(
            "Device code endpoint returned 404. "
            "The client_id may be invalid for GitHub's device flow."
        )

    if resp.status_code != 200:
        raise OAuthError(f"Device code request failed: {resp.status_code} {resp.text}")

    try:
        rj = resp.json()
    except Exception as e:
        raise OAuthError(f"Failed to parse device code response: {e}") from e

    if "device_code" not in rj or "user_code" not in rj:
        raise OAuthError(f"Invalid device code response: {rj}")

    return DeviceCodeResponse(
        device_code=rj["device_code"],
        user_code=rj["user_code"],
        verification_uri=rj.get("verification_uri_complete")
        or rj.get("verification_uri", "https://github.com/login/device"),
        interval=int(rj.get("interval", 5)),
    )


def poll_for_token(
    device_code: str,
    client_id: str = CLIENT_ID,
    interval: int = 5,
    cancel_event: "threading.Event | None" = None,
    timeout_seconds: int = DEFAULT_POLL_TIMEOUT_SECONDS,
) -> str:
    """Poll GitHub for access token after user authorizes.

    If cancel_event is provided and set, raises OAuthError("cancelled").
    If timeout_seconds is exceeded, raises OAuthError("Timed out waiting for authorization").
    """

    headers = {"Accept": "application/json"}
    data = {
        "client_id": client_id,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }

    poll_interval = interval
    start_time = time.time()

    while True:
        if time.time() - start_time > timeout_seconds:
            raise OAuthError("Timed out waiting for authorization")

        for _ in range(poll_interval * 10):
            if cancel_event and cancel_event.is_set():
                raise OAuthError("cancelled")
            time.sleep(0.1)

        if cancel_event and cancel_event.is_set():
            raise OAuthError("cancelled")

        try:
            resp = requests.post(ACCESS_TOKEN_URL, data=data, headers=headers, timeout=10)
        except requests.RequestException as e:
            raise OAuthError(f"Token request failed: {e}") from e

        try:
            jr = resp.json()
        except Exception as e:
            raise OAuthError(f"Failed to parse token response: {e}") from e

        if "error" in jr:
            err = jr["error"]
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                poll_interval += 2
                continue
            raise OAuthError(jr.get("error_description", err))

        access_token = jr.get("access_token")
        if not access_token:
            raise OAuthError(f"No access token in response: {jr}")

        return access_token


def exchange_for_copilot_token(github_token: str) -> CopilotCredentials:
    """Exchange a GitHub access token for a Copilot token."""
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {github_token}",
        **COPILOT_HEADERS,
    }

    try:
        resp = requests.get(COPILOT_TOKEN_URL, headers=headers, timeout=10)
    except requests.RequestException as e:
        logger.warning("Failed to exchange for Copilot token: %s", e)
        return CopilotCredentials(
            github_token=github_token, copilot_token=None, expires_ms=None
        )

    if resp.status_code != 200:
        logger.debug("Copilot token exchange returned %d", resp.status_code)
        return CopilotCredentials(
            github_token=github_token, copilot_token=None, expires_ms=None
        )

    try:
        data = resp.json()
    except Exception as e:
        logger.warning("Failed to parse Copilot token response: %s", e)
        return CopilotCredentials(
            github_token=github_token, copilot_token=None, expires_ms=None
        )

    token = data.get("token")
    expires_at = data.get("expires_at")

    if not isinstance(token, str):
        return CopilotCredentials(
            github_token=github_token, copilot_token=None, expires_ms=None
        )

    expires_ms = None
    if isinstance(expires_at, (int, float)):
        expires_ms = int(expires_at * 1000) - 5 * 60 * 1000

    return CopilotCredentials(
        github_token=github_token, copilot_token=token, expires_ms=expires_ms
    )


def get_copilot_base_url(token: str | None = None) -> str:
    """Get the Copilot API base URL from token or default."""
    if token:
        m = re.search(r"proxy-ep=([^;]+)", token)
        if m:
            proxy_host = m.group(1)
            api_host = re.sub(r"^proxy\.", "api.", proxy_host)
            return f"https://{api_host}"
    return "https://api.individual.githubcopilot.com"


def enable_model(token: str, model_id: str) -> bool:
    """Enable a model that requires policy acceptance."""
    base_url = get_copilot_base_url(token)
    url = f"{base_url}/models/{model_id}/policy"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "openai-intent": "chat-policy",
        "x-interaction-type": "chat-policy",
        **COPILOT_HEADERS,
    }
    try:
        r = requests.post(url, json={"state": "enabled"}, headers=headers, timeout=10)
        return r.ok
    except requests.RequestException as e:
        logger.debug("Failed to enable model %s: %s", model_id, e)
        return False


def enable_all_models(
    token: str,
    models: list[str] | None = None,
    on_progress: Callable[[str, bool], None] | None = None,
) -> None:
    """Enable a list of models."""
    if models is None:
        models = ["gpt-4o", "gpt-4o-mini", "claude-3.5-sonnet"]

    for m in models:
        success = enable_model(token, m)
        if on_progress:
            try:
                on_progress(m, success)
            except Exception as e:
                logger.debug("on_progress callback failed: %s", e)
        time.sleep(0.05)


def get_github_username(token: str) -> str | None:
    """Get the GitHub username for a token."""
    try:
        resp = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("login")
    except requests.RequestException as e:
        logger.debug("Failed to get GitHub username: %s", e)
    return None
