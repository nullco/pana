"""Pana — entry point and main application class."""
from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Callable

from pana import __version__ as _version
from pana.agents.agent import THINKING_LEVELS, Agent
from pana.ai.providers.factory import get_provider
from pana.app import theme as _theme
from pana.app import ui_themes
from pana.app.chat_themes import editor_theme
from pana.app.commands import default_registry
from pana.app.events import AgentChanged, EventBus, StreamAborted
from pana.app.extensions import (
    ExtensionAPI,
    ExtensionManager,
    InputEvent,
    SessionShutdownEvent,
    SessionStartEvent,
    discover_extension_paths,
    load_extension,
)
from pana.app.input_processing import strip_at_prefixes
from pana.app.stream_handler import StreamRenderer
from pana.state import state
from pana.tui.autocomplete import CombinedAutocompleteProvider, SlashCommand
from pana.tui.components.cancellable_loader import CancellableLoader
from pana.tui.components.editor import Editor, EditorOptions
from pana.tui.components.footer import Footer
from pana.tui.components.spacer import Spacer
from pana.tui.components.text import Text
from pana.tui.components.user_message import UserMessage
from pana.tui.terminal import ProcessTerminal
from pana.tui.theme import PanaTheme
from pana.tui.tui import TUI, Container

logger = logging.getLogger(__name__)


class PanaApp:
    """Manages the TUI app lifecycle and implements :class:`UIContext`."""

    def __init__(self, extension_paths: list[str] | None = None) -> None:
        self.agent: Agent | None = None
        self.hide_thinking_block: bool = state.get("hide_thinking_block", False)
        self._extension_paths = extension_paths or []
        self._extension_manager: ExtensionManager | None = None

        self.terminal = ProcessTerminal()
        self.tui = TUI(self.terminal)
        self._bus = EventBus(post_emit=self.tui.request_render)
        self._register_event_handlers()
        self._chat_container = Container()
        self._editor_container = Container()
        self._editor: Editor | None = None
        self._footer: Footer | None = None
        self._awaiting_response = False
        self._stream_task: asyncio.Task | None = None
        self._draining: bool = False
        self._pending_messages: list[str] = []

    def add_message(self, component: object) -> None:
        """Append *component* to the chat area and request a re-render."""
        self._chat_container.add_child(component)  # type: ignore[arg-type]
        self.tui.request_render()

    def remove_message(self, component: object) -> None:
        """Remove *component* from the chat area (no-op if absent)."""
        try:
            self._chat_container.remove_child(component)  # type: ignore[arg-type]
        except Exception:
            pass

    def show_selector(
        self, component: object, focus_target: object | None = None
    ) -> Callable[[], None]:
        """Swap the editor area for *component*; return a ``restore`` callable."""
        self._editor_container.clear()
        self._editor_container.add_child(component)  # type: ignore[arg-type]
        self.tui.set_focus(focus_target or component)  # type: ignore[arg-type]
        self.tui.request_render()

        def restore() -> None:
            self._editor_container.clear()
            self._editor_container.add_child(self._editor)  # type: ignore[arg-type]
            self.tui.set_focus(self._editor)  # type: ignore[arg-type]
            self.tui.request_render()

        return restore

    def update_footer(self) -> None:
        """Refresh the footer with current model / thinking-level info."""
        if self._footer:
            if self.agent:
                self._footer.set_model(self.agent.model_name, self.agent.provider_name)
                self._footer.set_thinking_level(self.agent.thinking_level)
            else:
                self._footer.set_model(None, None)
                self._footer.set_thinking_level(None)
            self.tui.request_render()

    def clear_chat(self) -> None:
        """Remove chat messages, keeping only the header row (first two items)."""
        if self.agent:
            self.agent.clear_history()
        self._chat_container.children[:] = self._chat_container.children[:2]
        self.tui.request_render()

    def stop(self) -> None:
        """Shut down the TUI."""
        self.tui.stop()

    def request_render(self) -> None:
        """Request an immediate TUI re-render."""
        self.tui.request_render()

    def set_agent(self, agent: Agent) -> None:
        """Replace the active agent, injecting the extension manager if available."""
        if self._extension_manager and agent._extension_manager is None:
            agent._extension_manager = self._extension_manager
            agent._agent = agent._build_agent()
        self.agent = agent
        self._bus.emit(AgentChanged())

    def set_hide_thinking_block(self, value: bool) -> None:
        """Set thinking-block visibility and persist it to state."""
        self.hide_thinking_block = value
        state.set("hide_thinking_block", value)

    def get_theme(self) -> PanaTheme:
        """Return the currently active :class:`~pana.tui.theme.PanaTheme`."""
        return _theme.get_current_theme()

    def notify(self, message: str, level: str = "info") -> None:
        """Display a notification message in the chat area.

        Supported *level* values: ``"info"``, ``"success"``, ``"error"``,
        ``"warning"``, ``"muted"``.  A spacer is appended automatically.
        """
        style_fn = {
            "error": _theme.error,
            "success": _theme.success,
            "warning": _theme.warning,
            "muted": _theme.dim,
        }.get(level, _theme.muted)
        self.add_message(Text(style_fn(message), padding_x=1, padding_y=0))
        self.add_message(Spacer(1))

    # ------------------------------------------------------------------
    # Internal event handlers
    # ------------------------------------------------------------------

    def _register_event_handlers(self) -> None:
        self._bus.on(AgentChanged, self._on_agent_changed)
        self._bus.on(StreamAborted, self._on_stream_aborted)

    def _on_agent_changed(self, _event: AgentChanged) -> None:
        self.update_footer()

    def _on_stream_aborted(self, _event: StreamAborted) -> None:
        self._awaiting_response = False
        self._draining = True
        self.tui.set_focus(self._editor)  # type: ignore[arg-type]

    # ------------------------------------------------------------------

    def _load_extensions(self) -> None:
        """Discover and load all extensions; register their commands."""
        self._extension_manager = ExtensionManager(ui=self)
        paths = discover_extension_paths(self._extension_paths)
        for path in paths:
            api = ExtensionAPI()
            if load_extension(path, api):
                self._extension_manager.add_api(api)
        # Register extension commands into the global registry
        for cmd_obj in self._extension_manager.build_command_objects():
            default_registry.register(cmd_obj)  # type: ignore[arg-type]

    def _setup_ui(self) -> None:
        self._footer = Footer(dim_fn=_theme.dim)

        fd_path = shutil.which("fd") or shutil.which("fdfind")

        slash_commands = [
            SlashCommand(name=name, description=desc)
            for name, desc in default_registry.completions().items()
        ]
        autocomplete = CombinedAutocompleteProvider(
            commands=slash_commands, fd_path=fd_path,
        )

        self._editor = Editor(
            self.tui, editor_theme,
            EditorOptions(padding_x=0, autocomplete_max_visible=5),
        )
        self._editor.set_autocomplete_provider(autocomplete)
        self._editor.on_submit = self._on_submit
        self._editor.on_action = self._on_action

        self._chat_container.add_child(
            Text(
                _theme.bold(_theme.accent("pana")) + " " + _theme.muted(f"v{_version}"),
                padding_x=0,
                padding_y=0,
            )
        )
        self._chat_container.add_child(Spacer(1))

        self._editor_container.add_child(self._editor)

        self.tui.add_child(self._chat_container)
        self.tui.add_child(self._editor_container)
        self.tui.add_child(self._footer)

        self.tui.set_focus(self._editor)

    def _on_action(self, action_id: str) -> None:
        if action_id == "app.thinking.cycle":
            self._cycle_thinking_level()
        elif action_id == "app.thinking.toggle":
            self._toggle_thinking_block_visibility()

    def _cycle_thinking_level(self) -> None:
        if not self.agent:
            self.notify("No model selected", "muted")
            return
        levels = list(THINKING_LEVELS)
        current = self.agent.thinking_level
        idx = levels.index(current) if current in levels else 0
        next_level = levels[(idx + 1) % len(levels)]
        self.agent.set_thinking_level(next_level)
        state.set("thinking_level", next_level)
        self.update_footer()
        self.notify(f"Thinking level: {next_level}", "muted")

    def _toggle_thinking_block_visibility(self) -> None:
        self.set_hide_thinking_block(not self.hide_thinking_block)
        label = "hidden" if self.hide_thinking_block else "visible"
        self.notify(f"Thinking blocks: {label}", "muted")

    async def _on_submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        if self._editor:
            self._editor.add_to_history(text)

        # Fire extension input event — handlers may transform, handle, or pass through
        if self._extension_manager and self._extension_manager.has_extensions:
            ext_ctx = self._extension_manager.make_context()
            input_event = InputEvent(text=text)
            result = await self._extension_manager.emit("input", input_event, ext_ctx)
            if isinstance(result, dict):
                action = result.get("action", "continue")
                if action == "handled":
                    return
                if action == "transform":
                    text = result.get("text", text)

        if text.startswith("/"):
            handled = await default_registry.dispatch(text, self)
            if not handled:
                self.notify(f"Unknown command: {text}", "error")
            return

        if not self.agent:
            self.notify("\u274c Please select a model first (/model)", "error")
            return

        self.add_message(Spacer(1))
        self.add_message(UserMessage(text, padding_x=1, padding_y=1, custom_bg_fn=_theme.user_msg_bg))

        if self._draining:
            self._pending_messages.append(text)
            self.tui.request_render()
            return

        self._stream_task = asyncio.create_task(self._stream_response(text))

    def _process_pending_messages(self) -> None:
        """Start the next queued message after a cancelled stream has drained."""
        if self._pending_messages and self.agent:
            next_text = self._pending_messages.pop(0)
            self._stream_task = asyncio.create_task(self._stream_response(next_text))

    async def _stream_response(self, user_text: str) -> None:
        if not self.agent or self._awaiting_response:
            return
        self._awaiting_response = True

        user_text = strip_at_prefixes(user_text)

        # Fire before_agent_start — extensions may inject extra system-prompt text
        if self._extension_manager and self._extension_manager.has_extensions:
            from pana.app.extensions.api import BeforeAgentStartEvent
            ext_ctx = self._extension_manager.make_context()
            before_event = BeforeAgentStartEvent(prompt=user_text)
            result = await self._extension_manager.emit(
                "before_agent_start", before_event, ext_ctx
            )
            if isinstance(result, dict) and "system_prompt" in result:
                self.agent.set_extra_system_prompt(str(result["system_prompt"]))
            else:
                self.agent.set_extra_system_prompt(None)

        cancel_event = asyncio.Event()
        loader = CancellableLoader(self.tui, _theme.accent, _theme.dim, "Working...")
        renderer = StreamRenderer(self, loader, cancel_event)

        loader.on_abort = renderer.on_abort
        self.add_message(loader)
        self.tui.set_focus(loader)

        _propagating_cancel = False
        try:
            await self.agent.stream(user_text, renderer.handle_event, cancel_event=cancel_event)

        except asyncio.CancelledError:
            _propagating_cancel = True
            renderer.mark_tools_error()
            self.notify("Operation aborted", "error")
            raise

        except Exception as e:
            logger.exception("Error during agent stream")
            if not cancel_event.is_set():
                renderer.mark_tools_error()
                renderer.show_error(e)
            self.tui.request_render()

        finally:
            renderer.cleanup()

            if cancel_event.is_set():
                self._draining = False
            else:
                self._awaiting_response = False
                self.tui.set_focus(self._editor)

            self._stream_task = None
            self.tui.request_render()

            if not _propagating_cancel:
                self._process_pending_messages()

    async def run(self) -> None:
        saved_theme = state.get("theme", "dark")
        try:
            ui_themes.apply_theme(saved_theme)
        except Exception:
            pass

        # Load extensions before building the agent so extension tools are included
        self._load_extensions()

        model_id = state.get("model")
        provider_name = state.get("provider")
        if model_id and provider_name:
            try:
                thinking_level = state.get("thinking_level", "medium")
                model = await get_provider(provider_name).build_model(model_id)
                self.agent = Agent(
                    model,
                    thinking_level=thinking_level,
                    extension_manager=self._extension_manager,
                )
            except Exception:
                pass

        self._setup_ui()
        self.update_footer()

        # Fire session_start after UI is ready
        if self._extension_manager and self._extension_manager.has_extensions:
            ext_ctx = self._extension_manager.make_context()
            await self._extension_manager.emit(
                "session_start", SessionStartEvent(), ext_ctx
            )

        try:
            await self.tui.start()
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            # Fire session_shutdown before TUI teardown
            if self._extension_manager and self._extension_manager.has_extensions:
                ext_ctx = self._extension_manager.make_context()
                try:
                    await self._extension_manager.emit(
                        "session_shutdown", SessionShutdownEvent(), ext_ctx
                    )
                except Exception:
                    pass
            if not self.tui.stopped:
                self.tui.stop()


async def main(extension_paths: list[str] | None = None) -> None:
    app = PanaApp(extension_paths=extension_paths)
    await app.run()


def run(extension_paths: list[str] | None = None) -> None:
    try:
        asyncio.run(main(extension_paths=extension_paths))
    finally:
        state.save()


if __name__ == "__main__":
    run()
