"""Mock provider for local development and tests."""

from __future__ import annotations

from typing import Optional

from .base import Provider


class MockProvider:
    name = "mock"

    def build_model(self, model_name: str | None = None):
        class MockModel:
            async def run(self, prompt, **kwargs):
                return {"id": "mock-1", "output": "mock response"}

            async def run_stream(self, prompt, message_history=None, **kwargs):
                # Return an async context manager that yields a result with
                # stream_output() and all_messages()
                class AsyncCtx:
                    async def __aenter__(self_non):
                        class Result:
                            async def stream_output(self_inner):
                                yield {"type": "delta", "text": "mock"}

                            def all_messages(self_inner):
                                return [{"role": "assistant", "content": "mock"}]

                        return Result()

                    async def __aexit__(self_non, exc_type, exc, tb):
                        return False

                return AsyncCtx()

        return MockModel()

    def get_authenticator(self) -> Optional[object]:
        return None

    def get_model_manager(self) -> Optional[object]:
        return None
