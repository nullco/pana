import asyncio
import logging
import os
import traceback

from dotenv import load_dotenv


from typing import Iterable

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.events import TextSelected
from textual.widgets import Footer, Header, Markdown, TextArea

from agent.agent import AgentInput, CodingAgent

load_dotenv()

_log_file = os.getenv("AGENT_LOG_FILE")
logging.basicConfig(
    level=os.getenv("AGENT_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(_log_file) if _log_file else logging.NullHandler()],
)
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

    UserInput:focus {
        border: round $primary-muted;
        background: transparent;
    }
    """

    class Submit(Message):
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


class CodingAgentApp(App):
    """A minimalist TUI for the Coding Agent."""

    TITLE = "Agent 007"
    BINDINGS = [
        Binding("ctrl+c", "handle_sigint", "Quit", show=False),
        Binding("c", "copy_focused", "Copy", show=True),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_sigint_time = 0.0
        self._background_tasks: set[asyncio.Task] = set()

    def action_handle_sigint(self) -> None:
        """Handle Ctrl+C: double-tap within 1s to quit, single clears session."""
        import time

        now = time.time()
        if now - self._last_sigint_time < 1.0:
            self._cancel_background_tasks()
            self.exit()
        else:
            self._last_sigint_time = now
            self.notify("Press Ctrl+C again to quit", severity="warning")

    def on_text_selected(self, event: TextSelected) -> None:
        """Auto-copy selected text to clipboard on mouse release."""
        selected = self.screen.get_selected_text()
        if not selected:
            return
        try:
            import pyperclip

            pyperclip.copy(selected)
        except Exception:
            self.copy_to_clipboard(selected)
        self.notify(f"Copied {len(selected)} characters")

    def action_copy_focused(self) -> None:
        """Copy the focused message to clipboard."""
        focused = self.focused
        if isinstance(focused, MessageOutput):
            focused.action_copy_to_clipboard()

    def _cancel_background_tasks(self) -> None:
        """Cancel all background tasks."""
        self.agent.copilot_auth.cancel()
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand("Login", "GitHub Copilot login", self._cmd_login)
        yield SystemCommand("Logout", "Clear authentication tokens", self._cmd_logout)
        yield SystemCommand("Status", "Show login status", self._cmd_status)
        yield SystemCommand("Clear", "Clear chat history", self._cmd_clear)

    def _cmd_login(self) -> None:
        result = self.agent.handle_command("/login")
        if result:
            asyncio.ensure_future(self._add_message(result))
        task = asyncio.create_task(self._poll_oauth())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _cmd_logout(self) -> None:
        result = self.agent.handle_command("/logout")
        if result:
            asyncio.ensure_future(self._add_message(result))

    def _cmd_status(self) -> None:
        result = self.agent.handle_command("/status")
        if result:
            asyncio.ensure_future(self._add_message(result))

    async def _cmd_clear(self) -> None:
        self.agent.clear_history()
        await self.chat_container.remove_children()
        await self._add_message("[Agent] Chat history cleared.")

    def compose(self) -> ComposeResult:
        yield Header(id="header")
        with Vertical(id="main"):
            yield ScrollableContainer(id="chat-container")
            yield UserInput(id="user_input")
        yield Footer(id="footer")

    def on_mount(self) -> None:
        self.input_widget = self.query_one("#user_input", UserInput)
        self.chat_container = self.query_one("#chat-container", ScrollableContainer)
        self.input_widget.focus()
        self.agent = CodingAgent()

    def on_descendant_focus(self, event) -> None:
        """Keep focus on the input widget at all times."""
        if not isinstance(event.widget, UserInput):
            self.input_widget.focus()

    async def _add_message(self, text: str) -> MessageOutput:
        """Add a message bubble to chat."""
        bubble = MessageOutput(text=text)
        await self.chat_container.mount(bubble)
        self.chat_container.scroll_end(animate=False)
        return bubble

    async def on_user_input_submit(self, message: UserInput.Submit) -> None:
        """Handle input submission."""
        user_text = message.text.strip()
        if not user_text:
            return

        self.input_widget.text = ""
        await self._handle_chat(user_text)

    async def _poll_oauth(self) -> None:
        """Poll for OAuth completion in background."""
        loop = asyncio.get_running_loop()
        _, msg = await loop.run_in_executor(
            None, self.agent.copilot_auth.poll_for_token
        )
        self.agent.refresh_model()
        await self._add_message(msg)

    async def _handle_chat(self, user_text: str) -> None:
        """Handle a regular chat message."""
        await self._add_message(user_text)
        bubble = await self._add_message("")

        try:

            def stream_handler(update):
                bubble.text = update
                self.chat_container.scroll_end(animate=False)

            await self.agent.stream(AgentInput(user_input=user_text), stream_handler)
        except Exception as e:
            logger.error("Error during agent stream: %s", e)
            logger.debug(traceback.format_exc())
            bubble.text = f"Error: {e}"
            self.chat_container.scroll_end(animate=False)


if __name__ == "__main__":
    CodingAgentApp().run()
