"""Copilot authenticator (migrated into ai.providers.copilot package)."""
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
    copilot_expires_ms: int | None = field(default=None, repr=False)
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

    def __post_init__(self) -> None:
        """Hydrate tokens from the environment if available."""
        if not self.github_token:
            self.github_token = os.getenv("GITHUB_API_KEY")
        if not self.copilot_token:
            self.copilot_token = os.getenv("COPILOT_API_KEY")
        if self.copilot_expires_ms is None:
            expires_env = os.getenv("COPILOT_EXPIRES_MS")
            if expires_env:
                try:
                    self.copilot_expires_ms = int(expires_env)
                except ValueError:
                    self.copilot_expires_ms = None

        if self.github_token and (not self.copilot_token or self.is_token_expired() or self.copilot_expires_ms is None):
            try:
                self._apply_copilot_token(self.github_token)
            except Exception:
                logger.debug("Failed to refresh Copilot token on init")

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

        self._apply_copilot_token(access_token)

        if os.getenv("AGENT_PERSIST_TOKENS", "true").lower() not in ("0", "false", "no"):
            self._save_tokens()

        username = copilot_oauth.get_github_username(access_token)
        if username:
            return True, f"[OAuth] Logged in as: {username}"
        return True, "[OAuth] Login successful!"

    def _apply_copilot_token(self, github_token: str) -> None:
        """Exchange GitHub token for Copilot token and store it."""
        creds = copilot_oauth.exchange_for_copilot_token(github_token)
        if creds.copilot_token:
            self.copilot_token = creds.copilot_token
            self.copilot_expires_ms = creds.expires_ms
            os.environ["COPILOT_API_KEY"] = creds.copilot_token
            if creds.expires_ms is not None:
                os.environ["COPILOT_EXPIRES_MS"] = str(creds.expires_ms)
            copilot_oauth.enable_all_models(creds.copilot_token)

    def is_token_expired(self) -> bool:
        """Check if the Copilot token has expired."""
        if not self.copilot_expires_ms:
            return False
        import time

        return int(time.time() * 1000) >= self.copilot_expires_ms

    def refresh_token(self) -> bool:
        """Refresh the Copilot token if expired or missing. Returns True if refreshed."""
        if not self.github_token:
            return False
        if self.copilot_token and self.copilot_expires_ms is not None and not self.is_token_expired():
            return False
        self._apply_copilot_token(self.github_token)
        return self.copilot_token is not None

    def logout(self) -> str:
        """Clear tokens and environment variables."""
        self.github_token = None
        self.copilot_token = None
        self._device_code = None

        if "GITHUB_API_KEY" in os.environ:
            del os.environ["GITHUB_API_KEY"]
        if "COPILOT_API_KEY" in os.environ:
            del os.environ["COPILOT_API_KEY"]
        if "COPILOT_EXPIRES_MS" in os.environ:
            del os.environ["COPILOT_EXPIRES_MS"]

        if os.getenv("AGENT_PERSIST_TOKENS", "true").lower() not in ("0", "false", "no"):
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
        if self.copilot_expires_ms is not None:
            existing["COPILOT_EXPIRES_MS"] = str(self.copilot_expires_ms)

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
                    if line.startswith("GITHUB_API_KEY=") or line.startswith("COPILOT_API_KEY=") or line.startswith("COPILOT_EXPIRES_MS="):
                        continue
                    lines.append(line)

            with open(env_path, "w") as f:
                f.writelines(lines)
        except Exception as e:
            logger.warning("Failed to remove tokens from .env: %s", e)
