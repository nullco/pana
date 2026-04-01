"""Pana — entry point and main application class."""
from __future__ import annotations

import asyncio
import logging
import re as _re
import shutil
from collections.abc import Callable

from pana import __version__ as _version
from pana.agents.agent import (
    THINKING_LEVELS,
    Agent,
    TextEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolCallUpdateEvent,
    ToolResultEvent,
)
from pana.ai.providers.factory import get_provider
from pana.app import theme as _theme
from pana.app import ui_themes
from pana.app.commands import default_registry
from pana.app.tool_renderer import ToolView, format_call, format_result
from pana.state import state
from pana.tui.autocomplete import CombinedAutocompleteProvider, SlashCommand
from pana.tui.components.box import Box
from pana.tui.components.cancellable_loader import CancellableLoader
from pana.tui.components.editor import Editor, EditorOptions, EditorTheme
from pana.tui.components.footer import Footer
from pana.tui.components.markdown import DefaultTextStyle, Markdown, MarkdownTheme
from pana.tui.components.spacer import Spacer
from pana.tui.components.text import Text
from pana.tui.terminal import ProcessTerminal
from pana.tui.tui import TUI, Container

logger = logging.getLogger(__name__)

_OSC133_ZONE_START = "\x1b]133;A\x07"
_OSC133_ZONE_END   = "\x1b]133;B\x07"
_OSC133_ZONE_FINAL = "\x1b]133;C\x07"

_AT_FILE_RE = _re.compile(r'@"([^"]+)"|@(\S+)')


def _strip_at_prefixes(text: str) -> str:
    """Strip ``@`` prefixes from file references so the LLM sees bare paths."""
    return _AT_FILE_RE.sub(lambda m: m.group(1) or m.group(2), text)


# ---------------------------------------------------------------------------
# Module-level UI themes that stay within main.py
# ---------------------------------------------------------------------------

_editor_theme = EditorTheme(
    border_color=_theme.border_muted,
    select_list=ui_themes.editor_select_theme,
)

_md_theme = MarkdownTheme(
    heading=_theme.heading,
    link=_theme.link,
    link_url=_theme.dim,
    code=_theme.accent,
    code_block=_theme.success,
    code_block_border=_theme.muted,
    quote=_theme.muted,
    quote_border=_theme.muted,
    hr=_theme.muted,
    list_bullet=_theme.accent,
    bold=_theme.bold,
    italic=_theme.italic,
    strikethrough=_theme.strikethrough,
    underline=_theme.underline,
    highlight_code=_theme.highlight_code,
)


# ---------------------------------------------------------------------------
# Chat bubble
# ---------------------------------------------------------------------------


class _UserMessage(Text):
    """User chat bubble with OSC 133 semantic zone markers."""

    def render(self, width: int) -> list[str]:
        lines = super().render(width)
        if not lines:
            return lines
        lines = list(lines)
        lines[0] = _OSC133_ZONE_START + lines[0]
        lines[-1] = lines[-1] + _OSC133_ZONE_END + _OSC133_ZONE_FINAL
        return lines


# ---------------------------------------------------------------------------
# MiniApp
# ---------------------------------------------------------------------------


class MiniApp:
    """Manages the TUI app lifecycle and implements :class:`CommandContext`."""

    def __init__(self) -> None:
        self.agent: Agent | None = None
        self.hide_thinking_block: bool = state.get("hide_thinking_block", False)

        self.terminal = ProcessTerminal()
        self.tui = TUI(self.terminal)
        self._chat_container = Container()
        self._editor_container = Container()
        self._editor: Editor | None = None
        self._footer: Footer | None = None
        self._awaiting_response = False
        self._stream_task: asyncio.Task | None = None
        self._draining: bool = False
        self._pending_messages: list[str] = []

    # ------------------------------------------------------------------
    # CommandContext implementation
    # ------------------------------------------------------------------

    def add_message(self, component: object) -> None:
        """Append *component* to the chat area and request a re-render."""
        self._chat_container.add_child(component)  # type: ignore[arg-type]
        self.tui.request_render()

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
        """Replace the active agent."""
        self.agent = agent

    def set_hide_thinking_block(self, value: bool) -> None:
        """Set thinking-block visibility and persist it to state."""
        self.hide_thinking_block = value
        state.set("hide_thinking_block", value)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

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
            self.tui, _editor_theme,
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

    # ------------------------------------------------------------------
    # Action handlers (keyboard shortcuts, not slash commands)
    # ------------------------------------------------------------------

    def _on_action(self, action_id: str) -> None:
        if action_id == "app.thinking.cycle":
            self._cycle_thinking_level()
        elif action_id == "app.thinking.toggle":
            self._toggle_thinking_block_visibility()

    def _cycle_thinking_level(self) -> None:
        if not self.agent:
            self.add_message(Text(_theme.muted("No model selected"), padding_x=1, padding_y=0))
            return
        levels = list(THINKING_LEVELS)
        current = self.agent.thinking_level
        idx = levels.index(current) if current in levels else 0
        next_level = levels[(idx + 1) % len(levels)]
        self.agent.set_thinking_level(next_level)
        state.set("thinking_level", next_level)
        self.update_footer()
        self.add_message(Text(_theme.muted(f"Thinking level: {next_level}"), padding_x=1, padding_y=0))
        self.tui.request_render()

    def _toggle_thinking_block_visibility(self) -> None:
        self.set_hide_thinking_block(not self.hide_thinking_block)
        label = "hidden" if self.hide_thinking_block else "visible"
        self.add_message(Text(_theme.muted(f"Thinking blocks: {label}"), padding_x=1, padding_y=0))
        self.tui.request_render()

    # ------------------------------------------------------------------
    # Input handler
    # ------------------------------------------------------------------

    async def _on_submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        if self._editor:
            self._editor.add_to_history(text)

        # Slash commands — delegate entirely to the registry.
        if text.startswith("/"):
            handled = await default_registry.dispatch(text, self)
            if not handled:
                self.add_message(
                    Text(_theme.error(f"Unknown command: {text}"), padding_x=1, padding_y=0)
                )
                self.add_message(Spacer(1))
            return

        # Chat message
        if not self.agent:
            self.add_message(
                Text(_theme.error("❌ Please select a model first (/model)"), padding_x=1, padding_y=0)
            )
            self.add_message(Spacer(1))
            return

        self.add_message(Spacer(1))
        self.add_message(_UserMessage(text, padding_x=1, padding_y=1, custom_bg_fn=_theme.user_msg_bg))

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

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def _stream_response(self, user_text: str) -> None:
        if not self.agent or self._awaiting_response:
            return
        self._awaiting_response = True

        user_text = _strip_at_prefixes(user_text)

        cancel_event = asyncio.Event()
        _handler_active = True

        tool_views: dict[str, ToolView] = {}
        fallback_tool_views: list[ToolView] = []

        md: Markdown | None = None
        thinking_md: Markdown | None = None
        thinking_placeholder: Text | None = None

        loader = CancellableLoader(self.tui, _theme.accent, _theme.dim, "Working...")

        def on_abort() -> None:
            nonlocal _handler_active
            cancel_event.set()
            _handler_active = False

            for tv in list(tool_views.values()) + fallback_tool_views:
                tv.box.set_bg_fn(_theme.tool_error_bg)

            loader.stop()
            try:
                self._chat_container.remove_child(loader)
            except Exception:
                pass
            self.add_message(Spacer(1))
            self.add_message(Text(_theme.error("Operation aborted"), padding_x=1, padding_y=0))

            self._awaiting_response = False
            self._draining = True
            self.tui.set_focus(self._editor)
            self.tui.request_render()

        loader.on_abort = on_abort
        self.add_message(loader)
        self.tui.set_focus(loader)

        def event_handler(event) -> None:
            nonlocal md, thinking_md, thinking_placeholder

            if not _handler_active:
                return

            self._chat_container.remove_child(loader)

            if isinstance(event, ThinkingEvent):
                if self.hide_thinking_block:
                    if thinking_placeholder is None:
                        self.add_message(Spacer(1))
                        thinking_placeholder = Text(
                            _theme.italic(_theme.thinking_text("Thinking...")),
                            padding_x=1,
                            padding_y=0,
                        )
                        self.add_message(thinking_placeholder)
                else:
                    if thinking_md is None:
                        self.add_message(Spacer(1))
                        thinking_md = Markdown(
                            "",
                            padding_x=1,
                            padding_y=0,
                            theme=_md_theme,
                            default_text_style=DefaultTextStyle(
                                color=_theme.thinking_text, italic=True
                            ),
                        )
                        self.add_message(thinking_md)
                    thinking_md.set_text(event.text)

                self.add_message(loader)
                self.tui.request_render()
                return

            thinking_md = None
            thinking_placeholder = None

            if isinstance(event, ToolCallEvent):
                md = None

                box = Box(padding_x=1, padding_y=1, bg_fn=_theme.tool_pending_bg)
                call_text = format_call(event.tool_name, event.args)
                call_text_component = Text(call_text, padding_x=0, padding_y=0)
                box.add_child(call_text_component)

                tv = ToolView(
                    tool_name=event.tool_name,
                    args=event.args,
                    box=box,
                    call_text_component=call_text_component,
                )

                self.add_message(Spacer(1))
                self.add_message(box)

                if event.tool_call_id:
                    tool_views[event.tool_call_id] = tv
                else:
                    fallback_tool_views.append(tv)

            elif isinstance(event, ToolCallUpdateEvent):
                tv = tool_views.get(event.tool_call_id) if event.tool_call_id else None
                if tv is not None:
                    tv.args = event.args
                    tv.call_text_component.set_text(format_call(event.tool_name, event.args))

            elif isinstance(event, ToolResultEvent):
                tv = None
                if event.tool_call_id:
                    tv = tool_views.get(event.tool_call_id)
                if tv is None and fallback_tool_views:
                    tv = fallback_tool_views.pop(0)

                if tv is not None:
                    if event.is_error:
                        tv.box.set_bg_fn(_theme.tool_error_bg)
                    else:
                        tv.box.set_bg_fn(_theme.tool_success_bg)

                    result_text = format_result(
                        tv.tool_name, tv.args,
                        event.result, event.elapsed_s, event.is_error,
                    )
                    if result_text is not None:
                        tv.box.add_child(Text(result_text, padding_x=0, padding_y=0))

            elif isinstance(event, TextEvent):
                if md is None:
                    self.add_message(Spacer(1))
                    md = Markdown("", padding_x=1, padding_y=0, theme=_md_theme)
                    self.add_message(md)
                md.set_text(event.text)

            self.add_message(loader)
            self.tui.request_render()

        _propagating_cancel = False
        try:
            await self.agent.stream(user_text, event_handler, cancel_event=cancel_event)

        except asyncio.CancelledError:
            _propagating_cancel = True
            for tv in list(tool_views.values()) + fallback_tool_views:
                tv.box.set_bg_fn(_theme.tool_error_bg)
            self.add_message(Spacer(1))
            self.add_message(Text(_theme.error("Operation aborted"), padding_x=1, padding_y=0))
            raise

        except Exception as e:
            logger.exception("Error during agent stream")
            if not cancel_event.is_set():
                for tv in list(tool_views.values()) + fallback_tool_views:
                    tv.box.set_bg_fn(_theme.tool_error_bg)
                err_md = Markdown("", padding_x=1, padding_y=0, theme=_md_theme)
                self.add_message(err_md)
                err_md.set_text(_theme.error(f"❌ {e}"))
            self.tui.request_render()

        finally:
            loader.stop()
            try:
                self._chat_container.remove_child(loader)
            except Exception:
                pass

            if cancel_event.is_set():
                self._draining = False
            else:
                self._awaiting_response = False
                self.tui.set_focus(self._editor)

            self._stream_task = None
            self.tui.request_render()

            if not _propagating_cancel:
                self._process_pending_messages()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self) -> None:
        saved_theme = state.get("theme", "dark")
        try:
            ui_themes.apply_theme(saved_theme)
        except Exception:
            pass

        model_id = state.get("model")
        provider_name = state.get("provider")
        if model_id and provider_name:
            try:
                thinking_level = state.get("thinking_level", "medium")
                model = await get_provider(provider_name).build_model(model_id)
                self.agent = Agent(model, thinking_level=thinking_level)
            except Exception:
                pass

        self._setup_ui()
        self.update_footer()
        try:
            await self.tui.run()
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            if not self.tui.stopped:
                self.tui.stop()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def main() -> None:
    app = MiniApp()
    await app.run()


def run() -> None:
    try:
        asyncio.run(main())
    finally:
        state.save()


if __name__ == "__main__":
    run()
