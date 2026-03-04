"""Minimalist TUI for the Coding Agent using Textual."""

from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from typing import Any, Callable, Iterable, TypeVar

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.events import TextSelected
from textual.screen import Screen
from textual.widgets import Footer, Header

from textual.command import CommandPalette

from app.config import AppConfig
from app.tui.commands import CommandHandler
from app.tui.providers import LoginProvider, ModelProvider
from app.tui.widgets import MessageOutput, UserInput
from app.tui.provider_selection import ProviderSelectionScreen

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


async def _run_in_daemon_thread(fn: Callable[[], _T]) -> _T:
    """Run *fn* in a plain daemon thread and await its result.

    Unlike ``loop.run_in_executor()``, threads started here are **not**
    registered in ``concurrent.futures.thread._threads_queues``.
    That global registry is drained by ``_python_exit()`` (a
    ``threading._register_atexit`` hook) which calls ``t.join()`` on every
    executor thread regardless of its daemon flag — causing the process to
    hang until the thread finishes.  A plain ``threading.Thread(daemon=True)``
    bypasses that registry entirely, so Python can exit immediately even if the
    OAuth poll is still sleeping.

    The caller is still responsible for signalling the thread to stop (via
    ``cancel_event``) for a *clean* shutdown; the daemon flag is the safety net
    that guarantees exit even when that signal is missed.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[_T] = loop.create_future()

    def _body() -> None:
        try:
            result = fn()
            if not loop.is_closed():
                loop.call_soon_threadsafe(future.set_result, result)
        except Exception as exc:  # noqa: BLE001
            if not loop.is_closed():
                loop.call_soon_threadsafe(future.set_exception, exc)

    thread = threading.Thread(target=_body, daemon=True, name="oauth-poll")
    thread.start()
    return await future


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
        if authenticator:
            authenticator.cancel()
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Provide system commands (accessible via command palette)."""
        yield from super().get_system_commands(screen)
        yield SystemCommand("Login", "Select provider and authenticate", self._cmd_login)
        yield SystemCommand("Logout", "Clear authentication tokens", self._cmd_logout)
        yield SystemCommand("Status", "Show login status", self._cmd_status)
        yield SystemCommand("Clear", "Clear chat history", self._cmd_clear)
        yield SystemCommand("Model", "List or select model", self._cmd_model)

    def _cmd_login(self) -> None:
        """Show command palette with login providers."""
        self.push_screen(CommandPalette(providers=[LoginProvider], placeholder="Select login provider…"))

    async def _login_with_provider(self, provider: str) -> None:
        """Login with a selected provider.
        
        Args:
            provider: Name of the provider to login with.
        """
        result = await self.command_handler.handle_login(provider)
        if result:
            await self._add_message(result)
        
        # Start OAuth polling in background
        task = asyncio.create_task(self._poll_oauth(provider))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _login_with_provider_sync(self, provider: str) -> None:
        """Callback for LoginProvider command palette hits."""
        asyncio.ensure_future(self._login_with_provider(provider))

    def _select_model(self, model_id: str, provider: str) -> None:
        """Callback for ModelProvider command palette hits."""
        ai = self.app_config.ai_manager
        if ai.provider_name() != provider:
            ai.switch_provider(provider)
        ai.select_model(model_id)
        self.app_config.rebuild_agent()
        self.notify(f"Switched to {model_id} ({provider})")

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

    def _cmd_model(self) -> None:
        """Show command palette with model selection."""
        self.push_screen(CommandPalette(providers=[ModelProvider], placeholder="Select model…"))

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
        
        # Check if Copilot tokens are available and show a helpful message if not
        import os
        if not os.getenv("COPILOT_API_KEY"):
            asyncio.ensure_future(self._show_auth_reminder())
        
        self.input_widget.focus()

    async def _show_auth_reminder(self) -> None:
        """Show authentication reminder if not logged in."""
        await asyncio.sleep(0.5)  # Let the UI settle first
        await self._add_message(
            "👋 Welcome to Agent 007!\n\n"
            "To use Copilot, you need to authenticate with GitHub.\n\n"
            "Type /login to get started, or use /help for more commands."
        )

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

    async def _poll_oauth(self, provider_name: str | None = None) -> None:
        """Poll for OAuth completion in background.
        
        Args:
            provider_name: Name of the provider to poll for. If None, uses current provider.
        """        
        if provider_name is None:
            provider_name = self.app_config.ai_manager.provider_name()
        
        authenticator = self.app_config.get_authenticator(provider_name)

        if not authenticator:
            return
            
        try:
            success, msg = await _run_in_daemon_thread(authenticator.poll_for_token)
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
            bubble.text = f"❌ {e}"
            self.chat_container.scroll_end(animate=False)


def run():
    """Run the TUI application."""
    app = CodingAgentApp()
    app.run()


if __name__ == "__main__":
    run()
