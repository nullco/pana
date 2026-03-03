"""Copilot provider that returns pydantic_ai OpenAIModel instances and exposes
Copilot authenticator and model manager.

This module implements the Provider interface for GitHub Copilot.
"""
from __future__ import annotations

from typing import Optional

from .base import Provider
from ai.providers.copilot.model import build_copilot_model
from ai.providers.copilot.auth import CopilotAuthenticator
from ai.providers.copilot.model_manager import ModelManager


class CopilotProvider(Provider):
    """GitHub Copilot AI provider."""

    name = "copilot"

    def build_model(self, model_name: str | None = None):
        """Return a pydantic_ai OpenAIModel configured for Copilot."""
        return build_copilot_model(model_name)

    def get_authenticator(self) -> Optional[CopilotAuthenticator]:
        """Return a CopilotAuthenticator instance."""
        return CopilotAuthenticator()

    def get_model_manager(self) -> Optional[ModelManager]:
        """Return a ModelManager bound to the provider's authenticator."""
        return ModelManager(authenticator=self.get_authenticator())
