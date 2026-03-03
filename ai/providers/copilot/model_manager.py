"""ModelManager for Copilot (migrated into provider package)."""
from __future__ import annotations

import logging
from typing import List, Optional

from . import copilot_oauth
from .models import get_available_models

logger = logging.getLogger(__name__)


class ModelManager:
    """Manage available models and current selection.

    This keeps a session-scoped current_model (string id) and a cached models list.
    """

    def __init__(self, authenticator: Optional[object] = None):
        self.auth = authenticator
        self._models_cache: List[dict] = []
        self.current_model: Optional[str] = None

    def _get_token(self) -> Optional[str]:
        # Prefer the authenticator's copilot token
        if self.auth and getattr(self.auth, "copilot_token", None):
            return self.auth.copilot_token

        # If authenticator has a GitHub token but no Copilot token, try to exchange it
        try:
            if self.auth and getattr(self.auth, "github_token", None):
                creds = copilot_oauth.exchange_for_copilot_token(self.auth.github_token)
                if creds and creds.copilot_token:
                    # apply to authenticator if possible
                    try:
                        self.auth.copilot_token = creds.copilot_token
                        self.auth.copilot_expires_ms = creds.expires_ms
                    except Exception:
                        pass
                    # set env fallback
                    import os

                    os.environ["COPILOT_API_KEY"] = creds.copilot_token
                    return creds.copilot_token
        except Exception:
            logger.debug("Failed to exchange github token for copilot token in ModelManager")

        # If there's a GitHub token set in environment, try to exchange it as well
        try:
            import os

            github_env = os.getenv("GITHUB_API_KEY") or os.getenv("GITHUB_TOKEN")
            if github_env:
                creds = copilot_oauth.exchange_for_copilot_token(github_env)
                if creds and creds.copilot_token:
                    os.environ["COPILOT_API_KEY"] = creds.copilot_token
                    return creds.copilot_token
        except Exception:
            logger.debug("Failed to exchange GITHUB_API_KEY from env for copilot token")

        # fallback to env variable COPILOT_API_KEY
        import os

        return os.getenv("COPILOT_API_KEY")

    def _default_config_path(self) -> str:
        import os

        cfg_dir = os.path.expanduser(os.getenv("AGENT_CONFIG_DIR", "~/.config/007"))
        try:
            os.makedirs(cfg_dir, exist_ok=True)
        except Exception:
            pass
        return os.path.join(cfg_dir, "model")

    def save_selected(self, path: str | None = None) -> None:
        """Persist the currently selected model to a simple file (optional).

        If path is None, uses AGENT_CONFIG_DIR or ~/.config/007/model
        """
        try:
            if not self.current_model:
                return
            if path is None:
                path = self._default_config_path()
            with open(path, "w") as f:
                f.write(self.current_model)
        except Exception:
            logger.debug("Failed to save selected model to %s", path)

    def load_selected(self, path: str | None = None) -> None:
        """Load selected model from a file if present.

        If path is None, uses AGENT_CONFIG_DIR or ~/.config/007/model
        """
        try:
            import os

            if path is None:
                path = self._default_config_path()
            if not os.path.exists(path):
                return
            with open(path) as f:
                v = f.read().strip()
                if v:
                    self.current_model = v
        except Exception:
            logger.debug("Failed to load selected model from %s", path)

    def get_models(self, refresh: bool = False) -> List[dict]:
        """Return list of available models. If refresh, re-fetch from the API."""
        token = self._get_token()
        if not token:
            logger.debug("No copilot token available when getting models")
            return []
        if refresh or not self._models_cache:
            # Ensure token is up-to-date if authenticator provided
            try:
                if self.auth and hasattr(self.auth, "refresh_token"):
                    self.auth.refresh_token()
            except Exception:
                logger.debug("Auth refresh failed when getting models")
            self._models_cache = get_available_models(token)
        return self._models_cache

    def select_model(self, model_id: str) -> bool:
        """Select a model by id. Returns True if selected, False otherwise."""
        if not model_id:
            return False
        # Refresh cache to validate
        models = self.get_models(refresh=False)
        for m in models:
            if m.get("id") == model_id or m.get("name") == model_id:
                self.current_model = m.get("id")
                return True
        # If not found, allow selecting by raw string (optimistic)
        self.current_model = model_id
        return True

    def enable_model(self, model_id: str) -> bool:
        """Attempt to accept policy / enable a model via Copilot API."""
        token = self._get_token()
        if not token:
            return False
        return copilot_oauth.enable_model(token, model_id)

    def refresh(self) -> List[dict]:
        """Force refresh of the models cache and return it."""
        return self.get_models(refresh=True)
