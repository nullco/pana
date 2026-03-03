"""Copilot provider package: contains auth, model builder, model manager, and helpers."""
from .model import build_copilot_model
from .auth import CopilotAuthenticator
from .model_manager import ModelManager
from .models import get_available_models


class CopilotProvider:
    """Provider adapter exposing build_model/get_authenticator/get_model_manager."""

    name = "copilot"

    def build_model(self, model_name: str | None = None):
        return build_copilot_model(model_name)

    def get_authenticator(self) -> CopilotAuthenticator:
        return CopilotAuthenticator()

    def get_model_manager(self) -> ModelManager:
        return ModelManager(authenticator=self.get_authenticator())


__all__ = [
    "build_copilot_model",
    "CopilotAuthenticator",
    "ModelManager",
    "get_available_models",
    "CopilotProvider",
]
