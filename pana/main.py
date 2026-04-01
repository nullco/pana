"""Minimalist terminal UI driven by a JSON theme system.

The active theme is loaded from ``pana/themes/<name>.json`` (built-in) or
from ``~/.pana/themes/`` / ``.pana/themes/`` (user / project overrides).
Use ``/theme`` to switch themes at runtime; the selection is persisted in
``~/.pana/state.json``.
"""
from __future__ import annotations

import asyncio
import logging
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
from pana.ai.providers.factory import get_provider, get_providers
from pana.app import theme as _theme
from pana.app.tool_renderer import ToolView, format_call, format_result, register
from pana.state import state
from pana.tui.autocomplete import CombinedAutocompleteProvider, SlashCommand
from pana.tui.components.box import Box
from pana.tui.components.cancellable_loader import CancellableLoader
from pana.tui.components.editor import Editor, EditorOptions, EditorTheme, SelectListTheme
from pana.tui.components.footer import Footer
from pana.tui.components.markdown import DefaultTextStyle, Markdown, MarkdownTheme
from pana.tui.components.select_list import SelectItem, SelectList
from pana.tui.components.select_list import SelectListTheme as SLTheme
from pana.tui.components.settings_list import SettingItem, SettingsList, SettingsListTheme
from pana.tui.components.spacer import Spacer
from pana.tui.components.text import Text
from pana.tui.terminal import ProcessTerminal
from pana.tui.theme import discover_themes
from pana.tui.tui import TUI, Container

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OSC 133 semantic zone markers (shell integration — mirrors pi-tui)
# ---------------------------------------------------------------------------

_OSC133_ZONE_START = "\x1b]133;A\x07"
_OSC133_ZONE_END   = "\x1b]133;B\x07"
_OSC133_ZONE_FINAL = "\x1b]133;C\x07"

# ---------------------------------------------------------------------------
# @file reference expansion
# ---------------------------------------------------------------------------

import re as _re

_AT_FILE_RE = _re.compile(r'@"([^"]+)"|@(\S+)')


def _strip_at_prefixes(text: str) -> str:
    """Strip ``@`` prefixes from file references so the LLM sees bare paths."""
    return _AT_FILE_RE.sub(lambda m: m.group(1) or m.group(2), text)


# ---------------------------------------------------------------------------
# UI theme objects — built with wrapper function references so that
# _theme.apply_theme() takes effect without rebuilding these objects.
# ---------------------------------------------------------------------------

_select_list_theme = SLTheme(
    selected_prefix=_theme.accent,
    selected_text=_theme.accent,
    description=_theme.muted,
    scroll_info=_theme.muted,
    no_match=_theme.muted,
)

_editor_select_theme = SelectListTheme(
    selected_prefix=_theme.accent,
    selected_text=_theme.accent,
    description=_theme.muted,
    scroll_info=_theme.muted,
    no_match=_theme.muted,
)

_editor_theme = EditorTheme(
    border_color=_theme.border_muted,
    select_list=_editor_select_theme,
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


def _make_settings_theme() -> SettingsListTheme:
    return SettingsListTheme(
        label=lambda s, sel: _theme.accent(s) if sel else s,
        value=lambda s, sel: _theme.accent(s) if sel else _theme.muted(s),
        description=_theme.muted,
        cursor=_theme.accent("❯ "),
        hint=_theme.dim,
    )


_settings_theme: SettingsListTheme = _make_settings_theme()


def _apply_theme(name: str) -> None:
    global _settings_theme
    _theme.apply_theme(name)
    _settings_theme = _make_settings_theme()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

COMMANDS: dict[str, str] = {
    "login":    "Authenticate with a provider",
    "model":    "Select a model",
    "settings": "Configure thinking level, display options, and theme",
    "new":      "Start a new session",
    "help":     "Show available commands",
    "quit":     "Exit",
}

_QUIT_ALIASES = ("quit", "exit", "q")


def _resolve_command(cmd: str) -> str:
    name = cmd.lstrip("/").lower()
    if name in COMMANDS or name in _QUIT_ALIASES:
        return name
    matches = [c for c in (set(COMMANDS) | set(_QUIT_ALIASES)) if c.startswith(name)]
    return matches[0] if len(matches) == 1 else name


# ---------------------------------------------------------------------------
# UserMessage component — mirrors UserMessageComponent with OSC 133 zones
# ---------------------------------------------------------------------------

class _UserMessage(Text):
    """User chat bubble: userMessageBg background + OSC 133 semantic zone markers."""

    def render(self, width: int) -> list[str]:
        lines = super().render(width)
        if not lines:
            return lines
        # Copy to avoid mutating the cached list from Text.render()
        lines = list(lines)
        # Wrap with OSC 133 shell-integration markers (mirrors user-message.js)
        lines[0] = _OSC133_ZONE_START + lines[0]
        lines[-1] = lines[-1] + _OSC133_ZONE_END + _OSC133_ZONE_FINAL
        return lines








# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class MiniApp:
    """Manages the TUI app lifecycle.

    Component tree mirrors the original pi-tui interactive mode:

        TUI
        ├── chatContainer      (header + messages)
        ├── editorContainer    (editor — swapped for selectors)
        └── footer             (cwd, model name right-aligned)
    """

    def __init__(self) -> None:
        self.agent: Agent | None = None
        self.terminal = ProcessTerminal()
        self.tui = TUI(self.terminal)
        self._chat_container = Container()
        self._editor_container = Container()
        self._editor: Editor | None = None
        self._footer: Footer | None = None
        self._awaiting_response = False
        self._stream_task: asyncio.Task | None = None
        self._hide_thinking_block: bool = state.get("hide_thinking_block", False)
        self._draining: bool = False          # True while a cancelled stream drains
        self._pending_messages: list[str] = []  # messages queued during drain

    def _setup_ui(self) -> None:
        # Footer — uses dim (#666666) for all text, matching theme.fg("dim", …)
        self._footer = Footer(dim_fn=_theme.dim)

        # Detect fd for fuzzy file completion
        fd_path = shutil.which("fd") or shutil.which("fdfind")

        # Slash commands for autocomplete
        slash_commands = [
            SlashCommand(name=name, description=desc)
            for name, desc in COMMANDS.items()
        ]
        autocomplete = CombinedAutocompleteProvider(
            commands=slash_commands, fd_path=fd_path,
        )

        # Editor — borderMuted (#505050) border, accent autocomplete theme
        self._editor = Editor(
            self.tui, _editor_theme,
            EditorOptions(padding_x=0, autocomplete_max_visible=5),
        )
        self._editor.set_autocomplete_provider(autocomplete)
        self._editor.on_submit = self._on_submit
        self._editor.on_action = self._on_action

        # Header: accent-colored title (mirrors pi-tui header style)
        self._chat_container.add_child(
            Text(_theme.bold(_theme.accent("pana")) + " " + _theme.muted(f"v{_version}"), padding_x=0, padding_y=0)
        )
        self._chat_container.add_child(Spacer(1))

        self._editor_container.add_child(self._editor)

        self.tui.add_child(self._chat_container)
        self.tui.add_child(self._editor_container)
        self.tui.add_child(self._footer)

        self.tui.set_focus(self._editor)

    def _update_footer(self) -> None:
        if self._footer:
            if self.agent:
                self._footer.set_model(self.agent.model_name, self.agent.provider_name)
                self._footer.set_thinking_level(self.agent.thinking_level)
            else:
                self._footer.set_model(None, None)
                self._footer.set_thinking_level(None)
            self.tui.request_render()

    def _show_selector(self, component: object, focus_target: object | None = None) -> Callable[[], None]:
        """Replace the editor with a selector component."""
        self._editor_container.clear()
        self._editor_container.add_child(component)  # type: ignore[arg-type]
        self.tui.set_focus(focus_target or component)  # type: ignore[arg-type]
        self.tui.request_render()

        def done() -> None:
            self._editor_container.clear()
            self._editor_container.add_child(self._editor)  # type: ignore[arg-type]
            self.tui.set_focus(self._editor)  # type: ignore[arg-type]
            self.tui.request_render()

        return done

    def _add_message(self, component: object) -> None:
        self._chat_container.add_child(component)  # type: ignore[arg-type]
        self.tui.request_render()

    def _on_action(self, action_id: str) -> None:
        if action_id == "app.thinking.cycle":
            self._cycle_thinking_level()
        elif action_id == "app.thinking.toggle":
            self._toggle_thinking_block_visibility()

    def _cycle_thinking_level(self) -> None:
        if not self.agent:
            self._add_message(
                Text(_theme.muted("No model selected"), padding_x=1, padding_y=0),
            )
            return
        levels = list(THINKING_LEVELS)
        current = self.agent.thinking_level
        idx = levels.index(current) if current in levels else 0
        next_level = levels[(idx + 1) % len(levels)]
        self.agent.set_thinking_level(next_level)
        state.set("thinking_level", next_level)
        self._update_footer()
        self._add_message(
            Text(_theme.muted(f"Thinking level: {next_level}"), padding_x=1, padding_y=0),
        )
        self.tui.request_render()

    def _toggle_thinking_block_visibility(self) -> None:
        self._hide_thinking_block = not self._hide_thinking_block
        state.set("hide_thinking_block", self._hide_thinking_block)
        label = "hidden" if self._hide_thinking_block else "visible"
        self._add_message(
            Text(_theme.muted(f"Thinking blocks: {label}"), padding_x=1, padding_y=0),
        )
        self.tui.request_render()

    def _on_submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        if self._editor:
            self._editor.add_to_history(text)

        # Slash commands
        if text.startswith("/"):
            cmd = _resolve_command(text)
            if cmd in _QUIT_ALIASES:
                self.tui.stop()
                return
            elif cmd == "new":
                if self.agent:
                    self.agent.clear_history()
                self._chat_container.children[:] = self._chat_container.children[:2]
                self._add_message(Text(_theme.dim("✓ New session started"), padding_x=1, padding_y=0))
                self.tui.request_render()
                return
            elif cmd == "login":
                asyncio.ensure_future(self._cmd_login())
                return
            elif cmd == "model":
                asyncio.ensure_future(self._cmd_model())
                return
            elif cmd == "settings":
                asyncio.ensure_future(self._cmd_settings())
                return
            elif cmd == "help":
                help_lines = [_theme.bold("Commands:")]
                for c, desc in COMMANDS.items():
                    help_lines.append(f"  {_theme.accent(f'/{c:<8}')} — {desc}")
                self._add_message(Text("\n".join(help_lines), padding_x=1, padding_y=0))
                self._add_message(Spacer(1))
                return
            else:
                self._add_message(
                    Text(_theme.error(f"Unknown command: {text}"), padding_x=1, padding_y=0)
                )
                self._add_message(Spacer(1))
                return

        # Chat message
        if not self.agent:
            self._add_message(
                Text(_theme.error("❌ Please select a model first (/model)"), padding_x=1, padding_y=0)
            )
            self._add_message(Spacer(1))
            return

        # User message bubble — shown immediately even when draining so the
        # user gets instant visual feedback that the message was received.
        self._add_message(Spacer(1))
        self._add_message(_UserMessage(text, padding_x=1, padding_y=1, custom_bg_fn=_theme.user_msg_bg))

        if self._draining:
            # The previous stream is still winding down after user cancel.
            # Queue this message; _process_pending_messages will send it once
            # the drain finishes.
            self._pending_messages.append(text)
            self.tui.request_render()
            return

        self._stream_task = asyncio.ensure_future(self._stream_response(text))

    def _process_pending_messages(self) -> None:
        """Start the next queued message after a cancelled stream has drained."""
        if self._pending_messages and self.agent:
            next_text = self._pending_messages.pop(0)
            self._stream_task = asyncio.ensure_future(self._stream_response(next_text))

    async def _stream_response(self, user_text: str) -> None:
        if not self.agent or self._awaiting_response:
            return
        self._awaiting_response = True

        # Strip @ prefixes so the LLM sees bare file paths
        user_text = _strip_at_prefixes(user_text)

        cancel_event = asyncio.Event()
        _handler_active = True  # flipped by on_abort to silence the event handler

        # Track tool views for bg color transitions
        tool_views: dict[str, ToolView] = {}
        fallback_tool_views: list[ToolView] = []

        # Markdown / thinking components — defined here so on_abort can see them
        md: Markdown | None = None
        thinking_md: Markdown | None = None
        thinking_placeholder: Text | None = None

        # Loader: accent spinner, dim message (mirrors BorderedLoader colors)
        loader = CancellableLoader(self.tui, _theme.accent, _theme.dim, "Working...")

        def on_abort() -> None:
            """Called synchronously when the user presses ESC.

            Sets the cancel_event so the streaming loop exits cleanly at the
            next token boundary, then immediately restores the UI so the user
            can type again without waiting for the network drain to finish.
            Messages submitted during the drain are queued and replayed once
            _stream_response's finally block calls _process_pending_messages.
            """
            nonlocal _handler_active
            cancel_event.set()
            _handler_active = False

            # Mark any in-progress tool boxes as errored
            for tv in list(tool_views.values()) + fallback_tool_views:
                tv.box.set_bg_fn(_theme.tool_error_bg)

            # Remove loader and show the aborted notice
            loader.stop()
            try:
                self._chat_container.remove_child(loader)
            except Exception:
                pass
            self._add_message(Spacer(1))
            self._add_message(Text(_theme.error("Operation aborted"), padding_x=1, padding_y=0))

            # Re-enable the editor immediately — the stream keeps draining in
            # the background but the user can already compose the next message.
            self._awaiting_response = False
            self._draining = True
            self.tui.set_focus(self._editor)
            self.tui.request_render()

        loader.on_abort = on_abort
        self._add_message(loader)
        self.tui.set_focus(loader)

        def event_handler(event) -> None:
            nonlocal md, thinking_md, thinking_placeholder

            # After on_abort fires, silently discard any further events that
            # arrive while the stream is still draining in the background.
            if not _handler_active:
                return

            # Keep loader pinned to the bottom: remove it, add new
            # content, then re-append it so it stays below everything.
            self._chat_container.remove_child(loader)

            if isinstance(event, ThinkingEvent):
                if self._hide_thinking_block:
                    if thinking_placeholder is None:
                        self._add_message(Spacer(1))
                        thinking_placeholder = Text(
                            _theme.italic(_theme.thinking_text("Thinking...")),
                            padding_x=1,
                            padding_y=0,
                        )
                        self._add_message(thinking_placeholder)
                else:
                    if thinking_md is None:
                        self._add_message(Spacer(1))
                        thinking_md = Markdown(
                            "",
                            padding_x=1,
                            padding_y=0,
                            theme=_md_theme,
                            default_text_style=DefaultTextStyle(
                                color=_theme.thinking_text, italic=True
                            ),
                        )
                        self._add_message(thinking_md)
                    thinking_md.set_text(event.text)

                self._add_message(loader)
                self.tui.request_render()
                return

            # Any non-thinking event resets the thinking component
            thinking_md = None
            thinking_placeholder = None

            if isinstance(event, ToolCallEvent):
                md = None

                # Create a Box with pending background
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

                self._add_message(Spacer(1))
                self._add_message(box)

                if event.tool_call_id:
                    tool_views[event.tool_call_id] = tv
                else:
                    fallback_tool_views.append(tv)

            elif isinstance(event, ToolCallUpdateEvent):
                # The early ToolCallEvent had partial/no args; now we have
                # the complete args — update the existing box in place.
                tv = tool_views.get(event.tool_call_id) if event.tool_call_id else None
                if tv is not None:
                    tv.args = event.args
                    tv.call_text_component.set_text(format_call(event.tool_name, event.args))

            elif isinstance(event, ToolResultEvent):
                # Find the matching tool view
                tv = None
                if event.tool_call_id:
                    tv = tool_views.get(event.tool_call_id)
                if tv is None and fallback_tool_views:
                    tv = fallback_tool_views.pop(0)

                if tv is not None:
                    # Transition bg color
                    if event.is_error:
                        tv.box.set_bg_fn(_theme.tool_error_bg)
                    else:
                        tv.box.set_bg_fn(_theme.tool_success_bg)

                    # Add result content if applicable
                    result_text = format_result(
                        tv.tool_name, tv.args,
                        event.result, event.elapsed_s, event.is_error,
                    )
                    if result_text is not None:
                        tv.box.add_child(
                            Text(result_text, padding_x=0, padding_y=0)
                        )

            elif isinstance(event, TextEvent):
                if md is None:
                    # Spacer(1) + Markdown (mirrors AssistantMessageComponent)
                    self._add_message(Spacer(1))
                    md = Markdown("", padding_x=1, padding_y=0, theme=_md_theme)
                    self._add_message(md)
                md.set_text(event.text)

            # Re-pin the loader below all new content
            self._add_message(loader)
            self.tui.request_render()

        _propagating_cancel = False
        try:
            await self.agent.stream(user_text, event_handler, cancel_event=cancel_event)

        except asyncio.CancelledError:
            # App-exit path: task.cancel() was called by asyncio.run() teardown.
            # on_abort was NOT called so the loader is still in the chat.
            _propagating_cancel = True
            for tv in list(tool_views.values()) + fallback_tool_views:
                tv.box.set_bg_fn(_theme.tool_error_bg)
            self._add_message(Spacer(1))
            self._add_message(Text(_theme.error("Operation aborted"), padding_x=1, padding_y=0))
            raise

        except Exception as e:
            logger.exception("Error during agent stream")
            if not cancel_event.is_set():
                for tv in list(tool_views.values()) + fallback_tool_views:
                    tv.box.set_bg_fn(_theme.tool_error_bg)
                err_md = Markdown("", padding_x=1, padding_y=0, theme=_md_theme)
                self._add_message(err_md)
                err_md.set_text(_theme.error(f"❌ {e}"))
            self.tui.request_render()

        finally:
            loader.stop()
            try:
                self._chat_container.remove_child(loader)
            except Exception:
                pass

            if cancel_event.is_set():
                # on_abort already restored the editor and set _draining=True.
                # Clear the draining flag now that the stream has fully unwound.
                self._draining = False
            else:
                # Normal completion or app-exit cancel: restore UI from here.
                self._awaiting_response = False
                self.tui.set_focus(self._editor)

            self._stream_task = None
            self.tui.request_render()

            if not _propagating_cancel:
                self._process_pending_messages()

    async def _cmd_login(self) -> None:
        providers = get_providers()
        if not providers:
            self._add_message(Text(_theme.error("No providers available."), padding_x=1, padding_y=0))
            self._add_message(Spacer(1))
            return

        items = [SelectItem(value=p, label=p) for p in providers]
        select = SelectList(items, 5, _select_list_theme, searchable=True)

        done_event = asyncio.Event()
        selected_provider: str | None = None

        def on_select(item: SelectItem) -> None:
            nonlocal selected_provider
            selected_provider = item.value
            restore()
            done_event.set()

        def on_cancel() -> None:
            restore()
            done_event.set()

        select.on_select = on_select
        select.on_cancel = on_cancel

        restore = self._show_selector(select)
        await done_event.wait()

        if selected_provider:
            try:
                await get_provider(selected_provider).authenticate(lambda result: None)
                self._add_message(
                    Text(_theme.success(f"Authenticated with {selected_provider}."), padding_x=1, padding_y=0)
                )
            except Exception as e:
                self._add_message(Text(_theme.error(f"Auth failed: {e}"), padding_x=1, padding_y=0))
            self._add_message(Spacer(1))

    async def _cmd_model(self) -> None:
        options: dict[str, tuple[str, str]] = {}
        for pname in get_providers():
            provider = get_provider(pname)
            if not provider.is_authenticated():
                continue
            for model_id in provider.get_models():
                options[f"{model_id} ({pname})"] = (model_id, pname)

        if not options:
            self._add_message(
                Text(_theme.error("No models available. Login first (/login)."), padding_x=1, padding_y=0)
            )
            self._add_message(Spacer(1))
            return

        items = [SelectItem(value=key, label=key) for key in options]
        select = SelectList(items, 8, _select_list_theme, searchable=True)

        done_event = asyncio.Event()
        selected_key: str | None = None

        def on_select(item: SelectItem) -> None:
            nonlocal selected_key
            selected_key = item.value
            restore()
            done_event.set()

        def on_cancel() -> None:
            restore()
            done_event.set()

        select.on_select = on_select
        select.on_cancel = on_cancel

        restore = self._show_selector(select)
        await done_event.wait()

        if selected_key and selected_key in options:
            model_id, provider_name = options[selected_key]
            try:
                model = await get_provider(provider_name).build_model(model_id)
                if self.agent:
                    self.agent.set_model(model)
                else:
                    thinking_level = state.get("thinking_level", "medium")
                    self.agent = Agent(model, thinking_level=thinking_level)
                state.set("provider", provider_name)
                state.set("model", model_id)
                self._add_message(
                    Text(_theme.success(f"Switched to {model_id} ({provider_name})."), padding_x=1, padding_y=0)
                )
                self._update_footer()
            except Exception as e:
                self._add_message(Text(_theme.error(f"Failed: {e}"), padding_x=1, padding_y=0))
            self._add_message(Spacer(1))

    async def _cmd_settings(self) -> None:
        current_theme_name = state.get("theme", "dark")

        def _theme_submenu(
            current_value: str,
            done: Callable[[str | None], None],
        ) -> SelectList:
            """Build a SelectList of all discoverable themes for the settings submenu."""
            theme_paths = discover_themes()
            sel_items = [
                SelectItem(
                    value=name,
                    label=(
                        f"{name}  {_theme.dim('← active')}"
                        if name == current_value
                        else f"{name}  {_theme.dim(str(theme_paths[name].parent))}"
                    ),
                )
                for name in sorted(theme_paths)
            ]
            select = SelectList(sel_items, 8, _select_list_theme, searchable=True)

            def on_select(item: SelectItem) -> None:
                done(item.value)

            def on_cancel() -> None:
                done(None)

            select.on_select = on_select
            select.on_cancel = on_cancel
            return select

        items = [
            SettingItem(
                id="thinking_level",
                label="Thinking level",
                current_value=state.get("thinking_level", "medium"),
                description="Reasoning depth for thinking-capable models",
                values=list(THINKING_LEVELS),
            ),
            SettingItem(
                id="hide_thinking_block",
                label="Hide thinking",
                current_value="true" if state.get("hide_thinking_block", False) else "false",
                description="Hide thinking blocks in assistant responses",
                values=["false", "true"],
            ),
            SettingItem(
                id="theme",
                label="Theme",
                current_value=current_theme_name,
                description=(
                    "Color theme for the UI. "
                    "Built-in: dark, light. "
                    "Custom themes: ~/.pana/themes/*.json or .pana/themes/*.json"
                ),
                submenu=_theme_submenu,
            ),
        ]

        done_event = asyncio.Event()

        def on_change(setting_id: str, value: str) -> None:
            if setting_id == "thinking_level":
                state.set("thinking_level", value)
                if self.agent:
                    self.agent.set_thinking_level(value)
                self._update_footer()
            elif setting_id == "hide_thinking_block":
                self._hide_thinking_block = value == "true"
                state.set("hide_thinking_block", self._hide_thinking_block)
            elif setting_id == "theme":
                try:
                    _apply_theme(value)
                    state.set("theme", value)
                    self.tui.request_render(force=True)
                except Exception as exc:
                    logger.warning("Failed to apply theme '%s': %s", value, exc)
            self.tui.request_render()

        def on_cancel() -> None:
            restore()
            done_event.set()

        settings_list = SettingsList(
            items, max_visible=8, theme=_settings_theme,
            on_change=on_change, on_cancel=on_cancel,
        )

        restore = self._show_selector(settings_list)
        await done_event.wait()

    async def run(self) -> None:
        # Restore saved theme (must happen before any UI renders)
        saved_theme = state.get("theme", "dark")
        try:
            _apply_theme(saved_theme)
        except Exception:
            pass  # missing/corrupt theme file — stay on dark

        # Restore saved model
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
        self._update_footer()
        self.tui.start()

        try:
            while not self.tui.stopped:
                await asyncio.sleep(0.1)
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
