"""OpenAI provider example (pydantic_ai-based).

Builds a pydantic_ai OpenAIModel using OPENAI_API_KEY from env.
"""
from __future__ import annotations

import os
from typing import Optional

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider as PydanticOpenAIProvider

from .base import Provider


class OpenAIProvider(Provider):
    """OpenAI API provider."""

    name = "openai"

    def build_model(self, model_name: str | None = None) -> OpenAIChatModel:
        model_name = model_name or os.getenv("AGENT_MODEL", "gpt-4.1")
        api_key = os.getenv("OPENAI_API_KEY")
        client = AsyncOpenAI(api_key=api_key)
        provider = PydanticOpenAIProvider(openai_client=client)
        return OpenAIChatModel(model_name, provider=provider)

    def get_authenticator(self) -> Optional[object]:
        return None

    def get_model_manager(self) -> Optional[object]:
        return None
