import logging

from pydantic_ai.agent import Agent as PydanticAgent

from ai.providers.model import Model

logger = logging.getLogger(__name__)


class Agent:

    def __init__(self, model: Model) -> None:
        self._model = model
        self._agent = PydanticAgent(model=model.instance)
        self._message_history = None

    @property
    def model_name(self) -> str:
        return self._model.name

    @property
    def provider_name(self) -> str:
        return self._model.provider.name

    def set_model(self, model: Model) -> None:
        self._model = model
        self._agent.model = model.instance

    def clear_history(self) -> None:
        self._message_history = None

    async def stream(self, user_input: str, stream_handler) -> None:
        if self._model.provider.should_reauthenticate():
            await self._model.provider.reauthenticate()
            model = await self._model.provider.build_model(self._model.name)
            self.set_model(model)
        async with self._agent.run_stream(
            user_input, message_history=self._message_history
        ) as result:
            async for update in result.stream_output():
                stream_handler(update)
            self._message_history = result.all_messages()
