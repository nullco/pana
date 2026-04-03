import asyncio
import time
from dataclasses import replace

from openai import AsyncOpenAI
from pydantic_ai.profiles.openai import openai_model_profile
from pydantic_ai.providers.openai import OpenAIProvider

from pana.ai.providers.copilot.responses import CopilotResponsesModel
from pana.ai.providers.model import Model
from pana.ai.providers.provider import Provider
from pana.state import state

from .auth import (
    COPILOT_HEADERS,
    exchange_for_copilot_token,
    get_copilot_base_url,
    poll_for_token,
    start_device_flow,
)


class CopilotProvider(Provider):

    name = "copilot"

    async def authenticate(self, handler):
        response = await asyncio.to_thread(start_device_flow)
        await handler(f"""[OAuth] Please visit {response.verification_uri}
Code: {response.user_code}""")

        async def poll():
            try:
                access_token = await asyncio.to_thread(poll_for_token, response.device_code)
                credentials = await asyncio.to_thread(exchange_for_copilot_token, access_token)
                state.set("copilot.github_access_token", credentials.github_token)
                state.set("copilot.access_token", credentials.copilot_token)
                state.set("copilot.expires_ms", credentials.expires_ms)
                await handler("[OAuth] Login successful!")
            except asyncio.CancelledError:
                await handler("[OAuth] Login cancelled.")
            except Exception as e:
                await handler(f"[OAuth] Login failed: {e}")

        asyncio.create_task(poll())

    def is_authenticated(self) -> bool:
        return bool(state.get("copilot.github_access_token"))

    def should_reauthenticate(self) -> bool:
        expires_ms = state.get("copilot.expires_ms")
        if not expires_ms:
            return True
        return expires_ms - int(time.time() * 1000) < 5 * 60 * 1000

    async def reauthenticate(self):
        github_token = state.get("copilot.github_access_token")
        if not github_token:
            return
        credentials = await asyncio.to_thread(exchange_for_copilot_token, github_token)
        state.set("copilot.access_token", credentials.copilot_token)
        state.set("copilot.expires_ms", credentials.expires_ms)

    async def build_model(self, model_name: str) -> Model:
        access_token = state.get("copilot.access_token")
        if not access_token:
            raise ValueError("Copilot token exchange failed — check your GitHub Copilot subscription")

        base_url = get_copilot_base_url(access_token)

        openai_client = AsyncOpenAI(
            base_url=base_url,
            api_key=access_token,
            default_headers=COPILOT_HEADERS,
        )
        provider = OpenAIProvider(openai_client=openai_client)
        profile = replace(
            openai_model_profile(model_name),
            openai_supports_strict_tool_definition=False,
            openai_supports_encrypted_reasoning_content=False,
        )
        model = CopilotResponsesModel(model_name, provider=provider, profile=profile)
        return Model(model_name, model, self)

    def get_models(self) -> list[str]:
        return [
            "gpt-5-mini",
            "gpt-4.1",
        ]
