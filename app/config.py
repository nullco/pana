"""Application configuration and dependency wiring."""

from __future__ import annotations

from agents import CodingAgent
from ai.manager import AIManager


class AppConfig:
    """Central configuration and wiring for the application.
    
    Manages the creation and lifecycle of core components:
    - AI Manager (provider abstraction)
    - Coding Agent (LLM interaction logic)
    - Command handling
    """

    def __init__(self, provider_name: str | None = None):
        """Initialize app configuration.
        
        Args:
            provider_name: Name of the AI provider to use.
                          If None, uses the default provider.
        """
        self.provider_name = provider_name
        self.ai_manager = AIManager(provider_name)
        self.agent = CodingAgent(provider_name=provider_name)

    def get_authenticator(self):
        """Get the current provider's authenticator."""
        return self.ai_manager.get_authenticator()

    def get_model_manager(self):
        """Get the current provider's model manager."""
        return self.ai_manager.get_model_manager()
