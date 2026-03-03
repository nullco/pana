"""Build Copilot-configured pydantic_ai OpenAIModel."""

from __future__ import annotations

import os

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .copilot_oauth import COPILOT_HEADERS, get_copilot_base_url


def build_copilot_model(model_name: str | None = None) -> OpenAIChatModel:
    """Build an OpenAI model client configured for the Copilot API."""
    model_name = model_name or os.getenv("AGENT_MODEL", "gpt-4.1")
    copilot_token = os.getenv("COPILOT_API_KEY") or "not-set"
    base_url = get_copilot_base_url(os.getenv("COPILOT_API_KEY"))

    openai_client = AsyncOpenAI(
        base_url=base_url,
        api_key=copilot_token,
        default_headers=COPILOT_HEADERS,
    )
    provider = OpenAIProvider(openai_client=openai_client)
    return OpenAIChatModel(model_name, provider=provider)
