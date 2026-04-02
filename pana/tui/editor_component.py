"""EditorComponent protocol.

This is the interface custom editors (e.g., vim mode) must implement to be
drop-in replacements for the built-in Editor.
"""
from __future__ import annotations

from collections.abc import Awaitable
from typing import TYPE_CHECKING, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pana.tui.autocomplete import AutocompleteProvider


@runtime_checkable
class EditorComponent(Protocol):
    """Interface for custom editor components.

    Allows extensions to provide their own editor implementation
    (e.g., vim mode, emacs mode, custom keybindings) while maintaining
    compatibility with the core application.
    """

    def render(self, width: int) -> list[str]: ...

    def invalidate(self) -> None: ...

    def get_text(self) -> str: ...

    def set_text(self, text: str) -> None: ...

    async def handle_input(self, data: str) -> None: ...

    on_submit: Callable[[str], Awaitable[None]] | None
    on_change: Callable[[str], None] | None

    def add_to_history(self, text: str) -> None: ...

    def insert_text_at_cursor(self, text: str) -> None: ...

    def get_expanded_text(self) -> str: ...

    def set_autocomplete_provider(self, provider: AutocompleteProvider) -> None: ...

    border_color: Callable[[str], str] | None

    def set_padding_x(self, padding: int) -> None: ...

    def set_autocomplete_max_visible(self, max_visible: int) -> None: ...
