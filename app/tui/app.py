"""Minimalist TUI for the Coding Agent using Textual."""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Iterable

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.events import TextSelected
from textual.screen import Screen
from textual.widgets import Footer, Header

from app.config import AppConfig
from app.tui.commands import CommandHandler
from app.tui.widgets import MessageOutput, UserInput

logger = logging.getLogger(__name__)


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
        self.app_config = AppConfig()
        self.command_handler = CommandHandler(self.app_config)

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
        authenticator = self.app_config.get_authenticator()
        if authenticator and hasattr(authenticator, "cancel"):
            authenticator.cancel()
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Provide system commands (accessible via command palette)."""
        yield from super().get_system_commands(screen)
        yield SystemCommand("Login", "GitHub Copilot login", self._cmd_login)
        yield SystemCommand("Logout", "Clear authentication tokens", self._cmd_logout)
        yield SystemCommand("Status", "Show login status", self._cmd_status)
        yield SystemCommand("Clear", "Clear chat history", self._cmd_clear)

    def _cmd_login(self) -> None:
        """Execute login command."""
        result = asyncio.ensure_future(self.command_handler.handle_login())
        asyncio.ensure_future(self._handle_command_result(result))
        
        # Start OAuth polling in background
        task = asyncio.create_task(self._poll_oauth())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _cmd_logout(self) -> None:
        """Execute logout command."""
        result = asyncio.ensure_future(self.command_handler.handle_logout())
        asyncio.ensure_future(self._handle_command_result(result))

    def _cmd_status(self) -> None:
        """Execute status command."""
        result = asyncio.ensure_future(self.command_handler.handle_status())
        asyncio.ensure_future(self._handle_command_result(result))

    async def _cmd_clear(self) -> None:
        """Execute clear command."""
        result = await self.command_handler.handle_clear()
        if result:
            await self._add_message(result)
        await self.chat_container.remove_children()

    async def _handle_command_result(self, result_future) -> None:
        """Handle command result from async execution."""
        try:
            result = await result_future
            if result:
                await self._add_message(result)
        except Exception as e:
            logger.error("Command execution failed: %s", e)
            await self._add_message(f"[Error] {e}")

    def compose(self) -> ComposeResult:
        """Compose the TUI layout."""
        yield Header(id="header")
        with Vertical(id="main"):
            yield ScrollableContainer(id="chat-container")
            yield UserInput(id="user_input")
        yield Footer(id="footer")

    def on_mount(self) -> None:
        """Initialize the app after mounting."""
        self.input_widget = self.query_one("#user_input", UserInput)
        self.chat_container = self.query_one("#chat-container", ScrollableContainer)
        self.input_widget.focus()

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

        # Check if it's a command
        if user_text.startswith("/"):
            await self._handle_slash_command(user_text)
        else:
            await self._handle_chat(user_text)

    async def _handle_slash_command(self, cmd: str) -> None:
        """Handle a slash command."""
        result = await self.command_handler.handle_command(cmd)
        if result:
            await self._add_message(result)

    async def _poll_oauth(self) -> None:
        """Poll for OAuth completion in background."""
        loop = asyncio.get_running_loop()
        authenticator = self.app_config.get_authenticator()
        
        if not authenticator or not hasattr(authenticator, "poll_for_token"):
            return
            
        try:
            success, msg = await loop.run_in_executor(
                None, authenticator.poll_for_token
            )
            await self._add_message(msg)
            
            # If OAuth was successful, refresh the agent with the new token
            if success:
                self.app_config.agent.refresh_agent()
                await self._add_message("[Agent] Ready to use! Try sending a message.")
        except Exception as e:
            logger.error("OAuth polling failed: %s", e)
            await self._add_message(f"[Error] OAuth polling failed: {e}")

    async def _handle_chat(self, user_text: str) -> None:
        """Handle a regular chat message."""
        await self._add_message(user_text)
        bubble = await self._add_message("")

        try:
            def stream_handler(update):
                bubble.text = update
                self.chat_container.scroll_end(animate=False)

            await self.app_config.agent.stream(user_text, stream_handler)
        except Exception as e:
            logger.error("Error during agent stream: %s", e)
            logger.debug(traceback.format_exc())
            bubble.text = f"Error: {e}"
            self.chat_container.scroll_end(animate=False)


def run():
    """Run the TUI application."""
    app = CodingAgentApp()
    app.run()


if __name__ == "__main__":
    run()
