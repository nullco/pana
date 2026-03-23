"""Minimalist terminal UI built on the pi-tui Python backport."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from collections.abc import Callable

from pygments import highlight as _pyg_highlight
from pygments.formatters import TerminalTrueColorFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound as _PygClassNotFound

from agents.agent import Agent
from ai.providers.factory import get_provider, get_providers
from state import state

from app.tui.autocomplete import AutocompleteItem, CombinedAutocompleteProvider, SlashCommand
from app.tui.components.editor import Editor, EditorOptions, EditorTheme, SelectListTheme
from app.tui.components.footer import Footer
from app.tui.components.loader import Loader
from app.tui.components.markdown import DefaultTextStyle, Markdown, MarkdownTheme
from app.tui.components.select_list import SelectItem, SelectList
from app.tui.components.select_list import SelectListTheme as SLTheme
from app.tui.components.spacer import Spacer
from app.tui.components.text import Text
from app.tui.terminal import ProcessTerminal
from app.tui.tui import TUI, Container

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------

def _user_msg_bg(s: str) -> str:
    """Dark blue-gray background matching the original pi-tui userMessageBg (#343541)."""
    return f"\x1b[48;2;52;53;65m{s}\x1b[49m"

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

    def _setup_ui(self) -> None:
        # Footer (cwd + model info, rendered below editor)
        self._footer = Footer(dim_fn=_dim)

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

        # Editor
        self._editor = Editor(
            self.tui, _editor_theme,
            EditorOptions(padding_x=0, autocomplete_max_visible=5),
        )
        self._editor.set_autocomplete_provider(autocomplete)
        self._editor.on_submit = self._on_submit

        # Build layout matching original pi-tui tree
        self._chat_container.add_child(
            Text(_bold(_cyan("Agent 007")) + " — mini mode", padding_x=0, padding_y=0)
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
            else:
                self._footer.set_model(None, None)
            self.tui.request_render()

    def _show_selector(self, component: object, focus_target: object | None = None) -> Callable[[], None]:
        """Replace the editor with a selector component, matching the original pi-tui pattern.

        Returns a ``done`` callback that restores the editor.
        """
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
        """Append a component to the chat container (above editor & footer)."""
        self._chat_container.add_child(component)  # type: ignore[arg-type]
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
                # Keep only the header (title + spacer) in chat container
                self._chat_container.children[:] = self._chat_container.children[:2]
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

        # Show user message with background (matching original pi-tui userMessageBg)
        self._add_message(Text(text, padding_x=1, padding_y=1, custom_bg_fn=_user_msg_bg))
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
                self._chat_container.remove_child(loader)
                md.set_text(update)
                self.tui.request_render()

            await self.agent.stream(user_text, stream_handler)

        except Exception as e:
            logger.exception("Error during agent stream")
            loader.stop()
            self._chat_container.remove_child(loader)
            md.set_text(_red(f"❌ {e}"))
            self.tui.request_render()
        finally:
            loader.stop()
            self._chat_container.remove_child(loader)
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
                    self.agent = Agent(model)
                state.set("provider", provider_name)
                state.set("model", model_id)
                self._add_message(
                    Text(_green(f"Switched to {model_id} ({provider_name})."), padding_x=1, padding_y=0)
                )
                self._update_footer()
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
        self._update_footer()
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
