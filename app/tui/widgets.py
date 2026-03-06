"""Textual widgets for the TUI."""

from __future__ import annotations

import logging

from textual.binding import Binding
from textual.message import Message
from textual.widgets import Markdown, TextArea

logger = logging.getLogger(__name__)


class MessageOutput(Markdown):
    """A Markdown widget for displaying rendered messages."""

    can_focus = False

    DEFAULT_CSS = """
    MessageOutput {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("y,c", "copy_to_clipboard", "Copy", show=False),
    ]

    def __init__(self, text: str = "", **kwargs):
        super().__init__(text, **kwargs)
        self._raw_text = text

    @property
    def text(self) -> str:
        """Get the raw markdown text."""
        return self._raw_text

    @text.setter
    def text(self, value: str) -> None:
        """Set the markdown text and update the rendered output."""
        self._raw_text = value
        self.update(value)

    def action_copy_to_clipboard(self) -> None:
        """Copy raw markdown text to clipboard."""
        if not self._raw_text:
            return
        try:
            import pyperclip

            pyperclip.copy(self._raw_text)
        except Exception as e:
            logger.debug("pyperclip failed, falling back to app clipboard: %s", e)
            self.app.copy_to_clipboard(self._raw_text)
        self.app.notify(f"Copied {len(self._raw_text)} characters")

    def on_click(self, event) -> None:
        """Focus this widget on click without copying (copy is handled by text selection)."""
        event.stop()


class UserInput(TextArea):
    """A TextArea for user input with command suggestions."""

    DEFAULT_CSS = """
    UserInput {
        height: auto;
        max-height: 10;
        margin: 0 1;
        border: round $primary-muted;
        background: transparent;
    }

    UserInput > .text-area--cursor-line {
        background: transparent;
    }

    UserInput:focus {
        border: round $primary-muted;
        background: transparent;
    }
    """

    class Submit(Message):
        """Message emitted when user submits input."""

        def __init__(self, text: str):
            self.text = text
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.language = None

    async def on_key(self, event) -> None:
        """Handle key events."""
        if event.key in ("shift+enter", "ctrl+n"):
            event.prevent_default()
            self.insert("\n")
        elif event.key == "enter":
            event.prevent_default()
            self.post_message(self.Submit(self.text))
        elif event.key == "slash" and not self.text:
            event.prevent_default()
            self.app.action_command_palette()
