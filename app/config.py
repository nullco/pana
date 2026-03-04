"""Application configuration and dependency wiring."""

from __future__ import annotations

from agents import CodingAgent
from ai.manager import AIManager
from ai.auth import AuthManager


class AppConfig:
    """Central configuration and wiring for the application.
    
    Manages the creation and lifecycle of core components:
    - AI Manager (provider abstraction)
    - Auth Manager (multi-provider authentication)
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
        self.auth_manager = AuthManager()
        self.agent = CodingAgent(
            provider=self.ai_manager.provider(),
            model_name=self.ai_manager.get_current_model(),
        )

    def get_authenticator(self, provider_name: str | None = None):
        """Get an authenticator for a provider.
        
        Args:
            provider_name: Name of the provider. If None, uses current provider.
            
        Returns:
            Authenticator instance, or None if not available.
        """
        if provider_name is None:
            provider_name = self.ai_manager.provider_name()
        return self.auth_manager.get_authenticator(provider_name)

    def get_model_manager(self):
        """Get the current provider's model manager."""
        return self.ai_manager.get_model_manager()

    def rebuild_agent(self):
        """Rebuild the agent with the current provider and model.
        
        Call this after switching providers or selecting a new model.
        """
        current_model = self.ai_manager.get_current_model()
        self.agent = CodingAgent(
            provider=self.ai_manager.provider(),
            model_name=current_model,
        )
