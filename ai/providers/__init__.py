"""Provider implementations for different AI backends (pydantic_ai specific).

This package exposes a factory to obtain providers. Providers are expected to
return pydantic_ai model instances from build_model(...).
"""
from .factory import get_provider

__all__ = ["get_provider"]
