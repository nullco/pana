"""Command handlers for the TUI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import AppConfig

logger = logging.getLogger(__name__)


class CommandHandler:
    """Handles slash commands in the TUI."""

    def __init__(self, app_config: AppConfig):
        """Initialize the command handler.
        
        Args:
            app_config: Application configuration with agent and authenticator.
        """
        self.app_config = app_config
        self.agent = app_config.agent
        self.authenticator = app_config.get_authenticator()

    async def handle_login(self) -> str | None:
        """Handle /login command."""
        if not self.authenticator:
            return "[Commands] No authenticator available for this provider"
        
        try:
            ok, msg = self.authenticator.start_login()
            return msg
        except Exception as e:
            logger.error("Login failed: %s", e)
            return f"[Commands] Login failed: {e}"

    async def handle_logout(self) -> str | None:
        """Handle /logout command."""
        if not self.authenticator:
            return "[Commands] No authenticator available for this provider"
        
        try:
            return self.authenticator.logout()
        except Exception as e:
            logger.error("Logout failed: %s", e)
            return f"[Commands] Logout failed: {e}"

    async def handle_status(self) -> str | None:
        """Handle /status command."""
        if not self.authenticator:
            return "[Commands] No authenticator available for this provider"
        
        try:
            status = self.authenticator.get_status()
            return f"[Agent] {status}"
        except Exception as e:
            logger.error("Status check failed: %s", e)
            return f"[Commands] Status check failed: {e}"

    async def handle_clear(self) -> str | None:
        """Handle /clear command."""
        try:
            self.agent.clear_history()
            return "[Agent] Chat history cleared."
        except Exception as e:
            logger.error("Clear history failed: %s", e)
            return f"[Commands] Clear failed: {e}"

    async def handle_command(self, cmd: str) -> str | None:
        """Handle a slash command.
        
        Args:
            cmd: Command string (e.g., "/login", "/status").
            
        Returns:
            Message to display, or None.
        """
        cmd = cmd.strip()
        
        if cmd == "/login":
            return await self.handle_login()
        elif cmd == "/logout":
            return await self.handle_logout()
        elif cmd == "/status":
            return await self.handle_status()
        elif cmd == "/clear":
            return await self.handle_clear()
        else:
            return "[Commands] Unknown command."
