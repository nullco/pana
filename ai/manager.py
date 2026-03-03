"""Small AI manager for provider interactions.

This module centralizes a thin wrapper around ai.providers.factory.get_provider
so callers can build models and access authenticators without importing
provider-specific modules.
"""

from __future__ import annotations

import logging
from typing import Optional

from ai.providers.factory import get_provider

logger = logging.getLogger(__name__)


class AIManager:
    def __init__(self, provider_name: str | None = None):
        self._provider_name = provider_name
        self._provider = get_provider(provider_name)
        self._model = None
        self._auth = None

    def provider(self):
        return self._provider

    def build_model(self, model_name: str | None = None):
        """Build (or rebuild) the provider model instance."""
        self._model = self._provider.build_model(model_name)
        return self._model

    def get_authenticator(self):
        if self._auth is None:
            self._auth = self._provider.get_authenticator()
        return self._auth

    def refresh_if_needed(self, model_name: str | None = None):
        """If the provider has an authenticator that can refresh tokens,
        attempt to refresh and rebuild the model when needed.
        """
        auth = self.get_authenticator()
        try:
            if auth and hasattr(auth, "refresh_token") and auth.refresh_token():
                logger.debug("auth.refresh_token() returned True — rebuilding model")
                return self.build_model(model_name)
        except Exception:
            logger.debug("auth.refresh_token() failed, ignoring")
        if not self._model:
            return self.build_model(model_name)
        return self._model
