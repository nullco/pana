"""Application-level UI protocol.

Defines the contract between the application layer (PanaApp) and anything
that needs to drive the UI — commands, extensions, and the agent layer.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pana.agents.agent import Agent
    from pana.tui.theme import PanaTheme


@runtime_checkable
class UIContext(Protocol):
    """Protocol describing all public UI operations the application exposes.

    Implemented by :class:`~pana.main.PanaApp`.  Extensions receive a
    ``UIContext`` via :attr:`ExtensionContext.ui` so they can interact
    with the full TUI without depending on a concrete class.
    """

    @property
    def agent(self) -> Agent | None: ...

    @property
    def hide_thinking_block(self) -> bool: ...

    def add_message(self, component: Any) -> None: ...

    def remove_message(self, component: Any) -> None: ...

    def show_selector(
        self, component: Any, focus_target: Any | None = None
    ) -> Callable[[], None]: ...

    def update_footer(self) -> None: ...

    def clear_chat(self) -> None: ...

    def stop(self) -> None: ...

    def request_render(self) -> None: ...

    def set_agent(self, agent: Agent) -> None: ...

    def set_hide_thinking_block(self, value: bool) -> None: ...

    def notify(self, message: str, level: str = "info") -> None: ...

    def get_theme(self) -> PanaTheme: ...
