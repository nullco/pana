from typing import Protocol

from ai.providers.model import Model


class Provider(Protocol):

    name: str

    async def authenticate(self, handler):
        ...

    async def reauthenticate(self):
        ...

    def is_authenticated(self) -> bool:
        ...

    def should_reauthenticate(self) -> bool:
        ...

    async def build_model(self, model_name: str) -> Model:
        ...

    def get_models(self) -> list[str]:
        ...
