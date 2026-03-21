"""Minimalist terminal UI built on the pi-tui Python backport."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys

from pygments import highlight as _pyg_highlight
from pygments.formatters import TerminalTrueColorFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound as _PygClassNotFound

from agents.agent import Agent
from ai.providers.factory import get_provider, get_providers
from state import state

from app.tui.autocomplete import AutocompleteItem, CombinedAutocompleteProvider, SlashCommand
from app.tui.components.editor import Editor, EditorOptions, EditorTheme, SelectListTheme
from app.tui.components.loader import Loader
from app.tui.components.markdown import DefaultTextStyle, Markdown, MarkdownTheme
from app.tui.components.select_list import SelectItem, SelectList
from app.tui.components.select_list import SelectListTheme as SLTheme
from app.tui.components.spacer import Spacer
from app.tui.components.text import Text
from app.tui.components.truncated_text import TruncatedText
from app.tui.terminal import ProcessTerminal
from app.tui.tui import TUI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------

def _cyan(s: str) -> str:
    return f"\x1b[36m{s}\x1b[0m"

def _dim(s: str) -> str:
    return f"\x1b[2m{s}\x1b[0m"

def _green(s: str) -> str:
    return f"\x1b[32m{s}\x1b[0m"

def _red(s: str) -> str:
    return f"\x1b[31m{s}\x1b[0m"

def _bold(s: str) -> str:
    return f"\x1b[1m{s}\x1b[0m"

def _italic(s: str) -> str:
    return f"\x1b[3m{s}\x1b[0m"

def _underline(s: str) -> str:
    return f"\x1b[4m{s}\x1b[0m"

def _strikethrough(s: str) -> str:
    return f"\x1b[9m{s}\x1b[0m"

def _yellow(s: str) -> str:
    return f"\x1b[33m{s}\x1b[0m"

def _magenta(s: str) -> str:
    return f"\x1b[35m{s}\x1b[0m"

def _gray(s: str) -> str:
    return f"\x1b[90m{s}\x1b[0m"

def _white(s: str) -> str:
    return f"\x1b[37m{s}\x1b[0m"

def _identity(s: str) -> str:
    return s

def _gold(s: str) -> str:
    return f"\x1b[38;2;240;198;116m{s}\x1b[0m"


# ---------------------------------------------------------------------------
# Syntax highlighting
# ---------------------------------------------------------------------------

_pyg_formatter = TerminalTrueColorFormatter(style="monokai")


def _highlight_code(code: str, lang: str | None) -> list[str]:
    """Syntax-highlight *code* using Pygments, matching the original pi-tui behaviour."""
    try:
        if lang:
            lexer = get_lexer_by_name(lang, stripall=True)
        else:
            lexer = guess_lexer(code)
    except _PygClassNotFound:
        return code.split("\n")
    highlighted = _pyg_highlight(code, lexer, _pyg_formatter)
    # Pygments adds a trailing newline; strip it so we don't get an extra blank line
    if highlighted.endswith("\n"):
        highlighted = highlighted[:-1]
    return highlighted.split("\n")


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

_select_list_theme = SLTheme(
    selected_prefix=_cyan,
    selected_text=_bold,
    description=_dim,
    scroll_info=_dim,
    no_match=_dim,
)

_editor_select_theme = SelectListTheme(
    selected_prefix=_cyan,
    selected_text=_bold,
    description=_dim,
    scroll_info=_dim,
    no_match=_dim,
)

_editor_theme = EditorTheme(
    border_color=_dim,
    select_list=_editor_select_theme,
)

_md_theme = MarkdownTheme(
    heading=_gold,
    link=_cyan,
    link_url=_dim,
    code=_yellow,
    code_block=_identity,
    code_block_border=_dim,
    quote=_dim,
    quote_border=_dim,
    hr=_dim,
    list_bullet=_cyan,
    bold=_bold,
    italic=_italic,
    strikethrough=_strikethrough,
    underline=_underline,
    highlight_code=_highlight_code,
)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

COMMANDS: dict[str, str] = {
    "login": "Authenticate with a provider",
    "model": "Select a model",
    "clear": "Clear chat history",
    "help": "Show available commands",
    "quit": "Exit",
}

_QUIT_ALIASES = ("quit", "exit", "q")


def _resolve_command(cmd: str) -> str:
    name = cmd.lstrip("/").lower()
    if name in COMMANDS or name in _QUIT_ALIASES:
        return name
    matches = [c for c in (set(COMMANDS) | set(_QUIT_ALIASES)) if c.startswith(name)]
    return matches[0] if len(matches) == 1 else name


# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------


class MiniApp:
    """Manages the TUI app lifecycle."""

    def __init__(self) -> None:
        self.agent: Agent | None = None
        self.terminal = ProcessTerminal()
        self.tui = TUI(self.terminal)
        self._messages_container = self.tui  # add messages directly to TUI
        self._editor: Editor | None = None
        self._status_bar: TruncatedText | None = None
        self._awaiting_response = False

    def _build_status(self) -> str:
        if self.agent:
            return f"{_dim(self.agent.model_name)} {_dim('·')} {_dim(self.agent.provider_name)}"
        return _dim("no model selected — /model to choose")

    def _setup_ui(self) -> None:
        # Status bar at bottom (will be re-added after messages)
        self._status_bar = TruncatedText(self._build_status())

        # Detect fd for fuzzy file completion
        fd_path = shutil.which("fd") or shutil.which("fdfind")

        # Slash commands for autocomplete (name-only; commands use overlay pickers)
        slash_commands = [
            SlashCommand(name=name, description=desc)
            for name, desc in COMMANDS.items()
        ]
        autocomplete = CombinedAutocompleteProvider(
            commands=slash_commands, fd_path=fd_path,
        )

        # Editor
        self._editor = Editor(
            self.tui, _editor_theme,
            EditorOptions(padding_x=0, autocomplete_max_visible=5),
        )
        self._editor.set_autocomplete_provider(autocomplete)
        self._editor.on_submit = self._on_submit

        # Build layout
        self.tui.add_child(Text(_bold(_cyan("Agent 007")) + " — mini mode", padding_x=0, padding_y=0))
        self.tui.add_child(Spacer(1))
        self.tui.add_child(self._status_bar)
        self.tui.add_child(Spacer(1))
        self.tui.add_child(self._editor)

        self.tui.set_focus(self._editor)

    def _update_status(self) -> None:
        if self._status_bar:
            self._status_bar = TruncatedText(self._build_status())
            # Replace the status bar in children (index 2)
            if len(self.tui.children) > 2:
                self.tui.children[2] = self._status_bar
            self.tui.request_render()

    def _add_message(self, component: object) -> None:
        """Insert a component before the editor (2nd-to-last child)."""
        idx = len(self.tui.children) - 1  # before editor
        self.tui.children.insert(idx, component)  # type: ignore[arg-type]
        self.tui.request_render()

    def _on_submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        if self._editor:
            self._editor.add_to_history(text)

        # Handle slash commands
        if text.startswith("/"):
            cmd = _resolve_command(text)
            if cmd in _QUIT_ALIASES:
                self.tui.stop()
                return
            elif cmd == "clear":
                if self.agent:
                    self.agent.clear_history()
                # Remove all children except title, spacer, status, spacer, editor
                self.tui.children[:] = self.tui.children[:2] + self.tui.children[-3:]
                self._add_message(Text(_dim("History cleared."), padding_x=1, padding_y=0))
                self.tui.request_render()
                return
            elif cmd == "login":
                asyncio.ensure_future(self._cmd_login())
                return
            elif cmd == "model":
                asyncio.ensure_future(self._cmd_model())
                return
            elif cmd == "help":
                help_lines = [_bold("Commands:")]
                for c, desc in COMMANDS.items():
                    help_lines.append(f"  {_cyan(f'/{c:<8}')} — {desc}")
                self._add_message(Text("\n".join(help_lines), padding_x=1, padding_y=0))
                self._add_message(Spacer(1))
                return
            else:
                self._add_message(
                    Text(_red(f"Unknown command: {text}"), padding_x=1, padding_y=0)
                )
                self._add_message(Spacer(1))
                return

        # Chat message
        if not self.agent:
            self._add_message(
                Text(_red("❌ Please select a model first (/model)"), padding_x=1, padding_y=0)
            )
            self._add_message(Spacer(1))
            return

        # Show user message
        self._add_message(Text(_dim("> ") + text, padding_x=1, padding_y=0))
        self._add_message(Spacer(1))

        asyncio.ensure_future(self._stream_response(text))

    async def _stream_response(self, user_text: str) -> None:
        if not self.agent or self._awaiting_response:
            return
        self._awaiting_response = True

        # Add loader
        loader = Loader(self.tui, _cyan, _dim, "Thinking...")
        self._add_message(loader)

        # Add markdown component (will be updated during streaming)
        md = Markdown("", padding_x=1, padding_y=0, theme=_md_theme)
        self._add_message(md)

        try:
            def stream_handler(update: str) -> None:
                loader.stop()
                # Remove loader if still present
                if loader in self.tui.children:
                    self.tui.children.remove(loader)
                md.set_text(update)
                self.tui.request_render()

            await self.agent.stream(user_text, stream_handler)

        except Exception as e:
            logger.exception("Error during agent stream")
            loader.stop()
            if loader in self.tui.children:
                self.tui.children.remove(loader)
            md.set_text(_red(f"❌ {e}"))
            self.tui.request_render()
        finally:
            loader.stop()
            if loader in self.tui.children:
                self.tui.children.remove(loader)
            self._awaiting_response = False
            self._add_message(Spacer(1))
            self.tui.request_render()

    async def _cmd_login(self) -> None:
        providers = get_providers()
        if not providers:
            self._add_message(Text(_red("No providers available."), padding_x=1, padding_y=0))
            self._add_message(Spacer(1))
            return

        items = [SelectItem(value=p, label=p) for p in providers]
        select = SelectList(items, 5, _select_list_theme, searchable=True)

        done_event = asyncio.Event()
        selected_provider: str | None = None

        def on_select(item: SelectItem) -> None:
            nonlocal selected_provider
            selected_provider = item.value
            self.tui.hide_overlay()
            done_event.set()

        def on_cancel() -> None:
            self.tui.hide_overlay()
            done_event.set()

        select.on_select = on_select
        select.on_cancel = on_cancel

        self.tui.show_overlay(select)  # type: ignore[arg-type]
        await done_event.wait()

        if selected_provider:
            try:
                await get_provider(selected_provider).authenticate(
                    lambda result: None
                )
                self._add_message(
                    Text(_green(f"Authenticated with {selected_provider}."), padding_x=1, padding_y=0)
                )
            except Exception as e:
                self._add_message(Text(_red(f"Auth failed: {e}"), padding_x=1, padding_y=0))
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
                Text(_red("No models available. Login first (/login)."), padding_x=1, padding_y=0)
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
            self.tui.hide_overlay()
            done_event.set()

        def on_cancel() -> None:
            self.tui.hide_overlay()
            done_event.set()

        select.on_select = on_select
        select.on_cancel = on_cancel

        self.tui.show_overlay(select)  # type: ignore[arg-type]
        await done_event.wait()

        if selected_key and selected_key in options:
            model_id, provider_name = options[selected_key]
            try:
                model = await get_provider(provider_name).build_model(model_id)
                if self.agent:
                    self.agent.set_model(model)
                else:
                    self.agent = Agent(model)
                state.set("provider", provider_name)
                state.set("model", model_id)
                self._add_message(
                    Text(_green(f"Switched to {model_id} ({provider_name})."), padding_x=1, padding_y=0)
                )
                self._update_status()
            except Exception as e:
                self._add_message(Text(_red(f"Failed: {e}"), padding_x=1, padding_y=0))
            self._add_message(Spacer(1))

    async def run(self) -> None:
        # Restore saved model
        model_id = state.get("model")
        provider_name = state.get("provider")
        if model_id and provider_name:
            try:
                model = await get_provider(provider_name).build_model(model_id)
                self.agent = Agent(model)
            except Exception:
                pass

        self._setup_ui()
        self.tui.start()

        # Keep running until TUI stops
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
