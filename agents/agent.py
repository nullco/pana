import logging

from pydantic_ai.agent import Agent as PydanticAgent

from agents.context import collect_agents_md
from ai.providers.model import Model

logger = logging.getLogger(__name__)


class Agent:

    def __init__(self, model: Model) -> None:
        self._model = model
        self._system_prompt = collect_agents_md()
        self._agent = self._build_agent()
        self._message_history = None

    def _build_agent(self) -> PydanticAgent:
        kwargs = {"model": self._model.instance}
        if self._system_prompt:
            kwargs["system_prompt"] = self._system_prompt
        return PydanticAgent(**kwargs)

    @property
    def model_name(self) -> str:
        return self._model.name

    @property
    def provider_name(self) -> str:
        return self._model.provider.name

    def set_model(self, model: Model) -> None:
        self._model = model
        self._agent = self._build_agent()

    def clear_history(self) -> None:
        self._message_history = None
        self._system_prompt = collect_agents_md()
        self._agent = self._build_agent()

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
