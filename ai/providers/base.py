"""Base Provider protocol for pydantic_ai-backed providers."""
from __future__ import annotations

from typing import Optional, Protocol

# Keep types loose to avoid heavy coupling in this module; concrete
# implementations will import pydantic_ai types directly.

class Provider(Protocol):
    """Provider that can build pydantic_ai model objects and expose optional auth/manager."""

    name: str

    def build_model(self, model_name: str | None = None):
        """Return a pydantic_ai model instance (e.g., OpenAIModel)."""
        ...

    def get_authenticator(self) -> Optional[object]:
        """Return an authenticator object used by the app (or None)."""
        ...

    def get_model_manager(self) -> Optional[object]:
        """Return a model manager object used by the app (or None)."""
        ...
