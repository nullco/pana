"""GitHub Copilot authentication handler."""

from __future__ import annotations

import logging
import os
import stat
import threading
from dataclasses import dataclass, field

from . import copilot_oauth

logger = logging.getLogger(__name__)


@dataclass
class CopilotAuthenticator:
    """Handles GitHub Copilot OAuth device flow."""

    github_token: str | None = None
    copilot_token: str | None = None
    _device_code: str | None = field(default=None, repr=False)
    _poll_interval: int = field(default=5, repr=False)
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _client_id: str = field(
        default_factory=lambda: os.getenv("GITHUB_OAUTH_CLIENT_ID", copilot_oauth.CLIENT_ID),
        repr=False,
    )
    _scope: str = field(
        default_factory=lambda: os.getenv("GITHUB_OAUTH_SCOPE", copilot_oauth.DEFAULT_SCOPE),
        repr=False,
    )

    def cancel(self) -> None:
        """Signal cancellation to any running poll."""
        self._cancel_event.set()

    def start_login(self) -> tuple[bool, str]:
        """Start the OAuth device flow. Returns (success, message)."""
        try:
            resp = copilot_oauth.start_device_flow(self._client_id, self._scope)
        except copilot_oauth.OAuthError as e:
            return False, f"[OAuth] Error: {e}"

        self._device_code = resp.device_code
        self._poll_interval = resp.interval

        return True, (
            f"[OAuth] Visit: {resp.verification_uri}\n"
            f"Code: {resp.user_code}\n"
            "Waiting for authorization..."
        )

    def poll_for_token(self) -> tuple[bool, str]:
        """Poll for token completion. Blocks until done. Returns (success, message)."""
        if not self._device_code:
            return False, "[OAuth] Login not started."

        self._cancel_event.clear()
        try:
            access_token = copilot_oauth.poll_for_token(
                self._device_code,
                self._client_id,
                self._poll_interval,
                self._cancel_event,
            )
        except copilot_oauth.OAuthError as e:
            if str(e) == "cancelled":
                return False, "[OAuth] Cancelled."
            return False, f"[OAuth] Error: {e}"

        self.github_token = access_token
        os.environ["GITHUB_API_KEY"] = access_token

        creds = copilot_oauth.exchange_for_copilot_token(access_token)
        if creds.copilot_token:
            self.copilot_token = creds.copilot_token
            os.environ["COPILOT_API_KEY"] = creds.copilot_token
            copilot_oauth.enable_all_models(creds.copilot_token)

        if os.getenv("AGENT_PERSIST_TOKENS", "").lower() in ("1", "true", "yes"):
            self._save_tokens()

        username = copilot_oauth.get_github_username(access_token)
        if username:
            return True, f"[OAuth] Logged in as: {username}"
        return True, "[OAuth] Login successful!"

    def logout(self) -> str:
        """Clear tokens and environment variables."""
        self.github_token = None
        self.copilot_token = None
        self._device_code = None

        if "GITHUB_API_KEY" in os.environ:
            del os.environ["GITHUB_API_KEY"]
        if "COPILOT_API_KEY" in os.environ:
            del os.environ["COPILOT_API_KEY"]

        if os.getenv("AGENT_PERSIST_TOKENS", "").lower() in ("1", "true", "yes"):
            self._remove_tokens_from_env_file()

        return "[OAuth] Logged out."

    def is_logged_in(self) -> bool:
        """Check if user is logged in."""
        return self.github_token is not None

    def get_status(self) -> str:
        """Get current login status."""
        if not self.github_token:
            return "Not logged in"
        username = copilot_oauth.get_github_username(self.github_token)
        if username:
            return f"Logged in as: {username}"
        return "Logged in"

    def _save_tokens(self) -> None:
        """Save tokens to .env file with restricted permissions."""
        env_path = os.path.join(os.getcwd(), ".env")
        existing: dict[str, str] = {}

        if os.path.exists(env_path):
            try:
                with open(env_path) as f:
                    for line in f:
                        if "=" in line:
                            k, v = line.rstrip("\n").split("=", 1)
                            existing[k] = v
            except Exception as e:
                logger.warning("Failed to read existing .env file: %s", e)

        if self.github_token:
            existing["GITHUB_API_KEY"] = self.github_token
        if self.copilot_token:
            existing["COPILOT_API_KEY"] = self.copilot_token

        try:
            with open(env_path, "w") as f:
                for k, v in existing.items():
                    f.write(f"{k}={v}\n")
            try:
                os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
            except OSError as e:
                logger.warning("Failed to set .env file permissions: %s", e)
        except Exception as e:
            logger.warning("Failed to save tokens to .env: %s", e)

    def _remove_tokens_from_env_file(self) -> None:
        """Remove tokens from .env file."""
        env_path = os.path.join(os.getcwd(), ".env")
        if not os.path.exists(env_path):
            return

        try:
            lines = []
            with open(env_path) as f:
                for line in f:
                    if line.startswith("GITHUB_API_KEY=") or line.startswith("COPILOT_API_KEY="):
                        continue
                    lines.append(line)

            with open(env_path, "w") as f:
                f.writelines(lines)
        except Exception as e:
            logger.warning("Failed to remove tokens from .env: %s", e)
