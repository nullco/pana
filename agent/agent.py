from __future__ import annotations

import os

from pydantic import BaseModel
from pydantic_ai.agent import Agent

from .auth import CopilotAuthenticator


class AgentInput(BaseModel):
    user_input: str


class CodingAgent(Agent):
    Input = AgentInput

    def __init__(self, model: str | None = None, **kwargs):
        model = model or os.getenv("AGENT_MODEL", "github:gpt-4.1")
        super().__init__(model=model, **kwargs)
        self._message_history = None
        self.copilot_auth = CopilotAuthenticator()

    async def stream(self, user_input: AgentInput, stream_handler):
        """Stream responses from the agent."""
        async with self.run_stream(
            user_input.user_input, message_history=self._message_history
        ) as result:
            async for update in result.stream_output():
                stream_handler(update)
            self._message_history = result.all_messages()

    def clear_history(self) -> None:
        """Clear the message history."""
        self._message_history = None

    def handle_command(self, cmd: str) -> str | None:
        """Handle slash commands. Returns a message or None."""
        cmd = cmd.strip()
        if cmd == "/login":
            ok, msg = self.copilot_auth.start_login()
            return msg
        if cmd == "/logout":
            return self.copilot_auth.logout()
        if cmd == "/status":
            return f"[Agent] {self.copilot_auth.get_status()}"
        return "[Agent] Unknown command."
