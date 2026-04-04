"""Internal event bus for decoupling side effects within PanaApp.

The ``EventBus`` is *not* part of the public ``UIContext`` protocol — it is an
implementation detail of :class:`~pana.main.PanaApp`.  Commands and extensions
interact with the UI through the imperative ``UIContext`` methods; internally
those methods may emit events so that unrelated subsystems (e.g. the footer)
can react without the caller knowing about them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Domain events
# ---------------------------------------------------------------------------


@dataclass
class AgentChanged:
    """The active agent was replaced or reconfigured."""


@dataclass
class StreamAborted:
    """The user aborted a running agent stream."""


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------


class EventBus:
    """Minimal synchronous publish/subscribe bus.

    After all handlers for an event have executed, the optional
    *post_emit* callback (typically ``tui.request_render``) is called
    **once** to coalesce rendering.
    """

    def __init__(self, post_emit: Callable[[], None] | None = None) -> None:
        self._handlers: dict[type, list[Callable]] = {}
        self._post_emit = post_emit

    def on(self, event_type: type, handler: Callable) -> None:
        """Register *handler* to be called whenever *event_type* is emitted."""
        self._handlers.setdefault(event_type, []).append(handler)

    def emit(self, event: object) -> None:
        """Dispatch *event* to all registered handlers, then post-emit."""
        for handler in self._handlers.get(type(event), []):
            handler(event)
        if self._post_emit is not None:
            self._post_emit()
