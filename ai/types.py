"""Shared AI protocols for providers, authenticators, and model managers."""

from __future__ import annotations

from typing import Protocol, Tuple, Optional, List


class Authenticator(Protocol):
    """Protocol for authentication implementations across providers."""

    def start_login(self) -> Tuple[bool, str]:
        ...

    def poll_for_token(self) -> Tuple[bool, str]:
        ...

    def is_logged_in(self) -> bool:
        ...

    def get_status(self) -> str:
        ...

    def logout(self) -> str:
        ...

    def refresh_token(self) -> bool:
        ...

    def is_token_expired(self) -> bool:
        ...

    def cancel(self) -> None:
        ...


class ModelManager(Protocol):
    """Protocol for provider model managers."""

    current_model: Optional[str]

    def get_models(self, refresh: bool = False) -> List[dict]:
        ...

    def select_model(self, model_id: str) -> bool:
        ...


class Provider(Protocol):
    """Protocol for AI providers."""

    name: str

    def build_model(self, model_name: str | None = None):
        ...

    def get_authenticator(self) -> Optional[Authenticator]:
        ...

    def get_model_manager(self) -> Optional[ModelManager]:
        ...
