"""Loader with Escape cancellation and abort signal."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable

from app.tui.keybindings import get_editor_keybindings
from app.tui.components.loader import Loader

if TYPE_CHECKING:
    from app.tui.tui import TUI


class CancellableLoader(Loader):
    def __init__(
        self,
        ui: TUI,
        spinner_color_fn: Callable[[str], str],
        message_color_fn: Callable[[str], str],
        message: str = "Working...",
    ) -> None:
        super().__init__(ui, spinner_color_fn, message_color_fn, message)
        self._cancelled = asyncio.Event()
        self.on_abort: Callable[[], None] | None = None

    @property
    def aborted(self) -> bool:
        return self._cancelled.is_set()

    @property
    def signal(self) -> asyncio.Event:
        """Cancellation signal — equivalent to AbortController.signal."""
        return self._cancelled

    def reset(self) -> None:
        self._cancelled = asyncio.Event()

    def handle_input(self, data: str) -> None:
        kb = get_editor_keybindings()
        if kb.matches(data, "selectCancel"):
            self._cancelled.set()
            if self.on_abort:
                self.on_abort()

    def dispose(self) -> None:
        self._cancelled.set()
        self.stop()
