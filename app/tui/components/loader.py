"""Animated loading spinner component."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable

from app.tui.components.text import Text

if TYPE_CHECKING:
    from app.tui.tui import TUI


class Loader(Text):
    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(
        self,
        ui: TUI,
        spinner_color_fn: Callable[[str], str],
        message_color_fn: Callable[[str], str],
        message: str = "Loading...",
    ) -> None:
        super().__init__("", padding_x=1, padding_y=0)
        self._ui = ui
        self._spinner_color_fn = spinner_color_fn
        self._message_color_fn = message_color_fn
        self._message = message
        self._current_frame = 0
        self._task: asyncio.Task | None = None
        self.start()

    def render(self, width: int) -> list[str]:
        return ["", *super().render(width)]

    def start(self) -> None:
        self._update_display()
        self._task = asyncio.ensure_future(self._animate())

    async def _animate(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.08)
                self._current_frame = (self._current_frame + 1) % len(self._FRAMES)
                self._update_display()
        except asyncio.CancelledError:
            pass

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def set_message(self, message: str) -> None:
        self._message = message
        self._update_display()

    def _update_display(self) -> None:
        frame = self._FRAMES[self._current_frame]
        self.set_text(
            f"{self._spinner_color_fn(frame)} {self._message_color_fn(self._message)}"
        )
        if self._ui:
            self._ui.request_render()
