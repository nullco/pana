import asyncio
import logging
import os
import traceback

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Footer, Header, Input, TextArea
from textual_autocomplete import AutoComplete, DropdownItem

from agent.agent import AgentInput, CodingAgent

logging.basicConfig(
    level=os.getenv("AGENT_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

COMMANDS = [
    DropdownItem(main="/help", prefix="❓ "),
    DropdownItem(main="/login", prefix="🔑 "),
    DropdownItem(main="/logout", prefix="🚪 "),
    DropdownItem(main="/status", prefix="📊 "),
    DropdownItem(main="/clear", prefix="🧹 "),
    DropdownItem(main="/quit", prefix="👋 "),
]

COMMANDS_HELP = """Available commands:
  /help   - Show this help message
  /login  - Start GitHub Copilot OAuth device flow
  /logout - Clear authentication tokens
  /status - Show login status
  /clear  - Clear chat history
  /quit   - Quit the application"""


class MessageOutput(TextArea):
    """A TextArea for displaying messages."""

    DEFAULT_CSS = """
    MessageOutput {
        height: auto;
        overflow: hidden;
    }
    """

    BINDINGS = [
        Binding("y,c", "copy_to_clipboard", "Copy", show=False),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.read_only = True
        self.language = "markdown"

    def action_copy_to_clipboard(self) -> None:
        """Copy selected text or all text to clipboard."""
        text = self.selected_text or self.text
        if not text:
            return
        try:
            import pyperclip

            pyperclip.copy(text)
        except Exception as e:
            logger.debug("pyperclip failed, falling back to app clipboard: %s", e)
            self.app.copy_to_clipboard(text)
        self.app.notify(f"Copied {len(text)} characters")


class CommandAutoComplete(AutoComplete):
    """AutoComplete that only shows suggestions for slash commands."""

    def get_candidates(self, target_state):
        """Only show command suggestions when input starts with /."""
        if target_state.text.startswith("/"):
            return COMMANDS
        return []


class CodingAgentApp(App):
    """A minimalist TUI for the Coding Agent."""

    TITLE = "Agent 007"
    CSS = """
    #user_input {
        dock: bottom;
        height: auto;
        min-height: 3;
        margin: 0 1;
    }

    AutoComplete {
        max-height: 10;
    }
    """
    BINDINGS = [Binding("ctrl+c", "handle_sigint", "Quit", show=False)]

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

    def _cancel_background_tasks(self) -> None:
        """Cancel all background tasks."""
        self.agent.copilot_auth.cancel()
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()

    def compose(self) -> ComposeResult:
        yield Header(id="header")
        with Vertical(id="main"):
            yield ScrollableContainer(id="chat-container")
            user_input = Input(
                placeholder="Enter your prompt (/ for commands)...",
                id="user_input",
            )
            yield user_input
            yield CommandAutoComplete(target=user_input, candidates=None)
        yield Footer(id="footer")

    def on_mount(self) -> None:
        self.input_widget = self.query_one("#user_input", Input)
        self.chat_container = self.query_one("#chat-container", ScrollableContainer)
        self.input_widget.focus()
        self.agent = CodingAgent()

    async def _add_message(self, text: str) -> MessageOutput:
        """Add a message bubble to chat."""
        bubble = MessageOutput(text=text)
        await self.chat_container.mount(bubble)
        self.chat_container.scroll_end(animate=False)
        return bubble

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        user_text = event.value.strip()
        if not user_text:
            return

        self.input_widget.value = ""

        if user_text.startswith("/"):
            await self._handle_command(user_text)
            return

        await self._handle_chat(user_text)

    async def _handle_command(self, cmd: str) -> None:
        """Handle slash commands."""
        cmd_name = cmd.split()[0]

        if cmd_name == "/quit":
            self._cancel_background_tasks()
            self.exit()
            return

        if cmd_name == "/help":
            await self._add_message(COMMANDS_HELP)
            return

        if cmd_name == "/clear":
            self.agent.clear_history()
            await self.chat_container.remove_children()
            await self._add_message("[Agent] Chat history cleared.")
            return

        if cmd_name == "/login":
            result = self.agent.handle_command(cmd_name)
            if result:
                await self._add_message(result)
            task = asyncio.create_task(self._poll_oauth())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            return

        if cmd_name in ("/logout", "/status"):
            result = self.agent.handle_command(cmd_name)
            if result:
                await self._add_message(result)
            return

        await self._add_message(f"[Agent] Unknown command: {cmd_name}\n\n{COMMANDS_HELP}")

    async def _poll_oauth(self) -> None:
        """Poll for OAuth completion in background."""
        loop = asyncio.get_running_loop()
        _, msg = await loop.run_in_executor(
            None, self.agent.copilot_auth.poll_for_token
        )
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
