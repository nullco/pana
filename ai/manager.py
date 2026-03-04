"""Small AI manager for provider interactions.

This module centralizes a thin wrapper around ai.providers.factory.get_provider
so callers can build models and access authenticators without importing
provider-specific modules.
"""

from __future__ import annotations

import logging
from typing import Optional

from ai.providers.factory import get_provider
from ai.types import ModelManager

logger = logging.getLogger(__name__)

# Available providers
AVAILABLE_PROVIDERS = ["copilot", "openai"]


class AIManager:
    def __init__(self, provider_name: str | None = None):
        self._provider_name = provider_name or "copilot"
        self._provider = get_provider(self._provider_name)
        self._model = None
        self._auth = None

    def provider(self):
        return self._provider

    def provider_name(self) -> str:
        """Get the current provider name."""
        return self._provider_name

    def build_model(self, model_name: str | None = None):
        """Build (or rebuild) the provider model instance."""
        self._model = self._provider.build_model(model_name)
        return self._model

    def get_authenticator(self):
        if self._auth is None:
            self._auth = self._provider.get_authenticator()
        return self._auth

    def get_model_manager(self) -> Optional[ModelManager]:
        """Get the current provider's model manager."""
        return self._provider.get_model_manager()

    def switch_provider(self, provider_name: str) -> bool:
        """Switch to a different provider.
        
        Args:
            provider_name: Name of the provider to switch to.
            
        Returns:
            True if switch was successful, False otherwise.
        """
        if provider_name not in AVAILABLE_PROVIDERS:
            logger.warning("Unknown provider: %s", provider_name)
            return False
        
        try:
            self._provider_name = provider_name
            self._provider = get_provider(provider_name)
            self._model = None
            self._auth = None
            return True
        except Exception as e:
            logger.error("Failed to switch provider: %s", e)
            return False

    def get_available_providers(self) -> list[str]:
        """Get list of available providers."""
        return AVAILABLE_PROVIDERS.copy()

    def get_all_models(self, refresh: bool = False) -> list[dict]:
        """Get all available models from all providers.
        
        Args:
            refresh: If True, force refresh from API for each provider.
            
        Returns:
            List of model dicts with 'provider' field added.
        """
        all_models = []
        
        for provider_name in AVAILABLE_PROVIDERS:
            try:
                provider = get_provider(provider_name)
                model_manager = provider.get_model_manager()

                if model_manager:
                    models = model_manager.get_models(refresh=refresh)
                    for model in models:
                        model["provider"] = provider_name
                    all_models.extend(models)
            except Exception as e:
                logger.debug("Failed to get models from provider %s: %s", provider_name, e)
        
        return all_models

    def get_available_models(self, refresh: bool = False) -> list[dict]:
        """Get list of available models for current provider.
        
        Args:
            refresh: If True, force refresh from API.
            
        Returns:
            List of model dicts, or empty list if not supported by provider.
        """
        model_manager = self.get_model_manager()
        if not model_manager:
            return []
        
        try:
            return model_manager.get_models(refresh=refresh)
        except Exception as e:
            logger.debug("Failed to get available models: %s", e)
            return []

    def select_model(self, model_id: str) -> bool:
        """Select a model.
        
        Args:
            model_id: ID or name of the model to select.
            
        Returns:
            True if model was selected, False otherwise.
        """
        model_manager = self.get_model_manager()
        if not model_manager:
            return False
        
        try:
            return model_manager.select_model(model_id)
        except Exception as e:
            logger.debug("Failed to select model: %s", e)
            return False

    def get_current_model(self) -> Optional[str]:
        """Get the currently selected model ID."""
        model_manager = self.get_model_manager()
        if not model_manager:
            return None
        
        return model_manager.current_model

    def refresh_if_needed(self, model_name: str | None = None):
        """If the provider has an authenticator that can refresh tokens,
        attempt to refresh and rebuild the model when needed.
        """
        auth = self.get_authenticator()
        try:
            if auth and auth.refresh_token():
                logger.debug("auth.refresh_token() returned True — rebuilding model")
                return self.build_model(model_name)
        except Exception:
            logger.debug("auth.refresh_token() failed, ignoring")
        if not self._model:
            return self.build_model(model_name)
        return self._model
