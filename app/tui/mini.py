"""Minimalist terminal UI — look and feel matches original pi-tui dark theme exactly.

Colors sourced from dark.json (pi-tui):
  accent       #8abeb7   sage teal  (select prefix/text, list bullet, inline code)
  border       #5f87ff   blue
  borderMuted  #505050   dark gray  (editor border)
  muted        #808080   medium gray (descriptions, scroll info, quotes, hr, code border)
  dim          #666666   dim gray   (footer, link url, muted decorations)
  success      #b5bd68   olive green (code blocks)
  error        #cc6666   muted red
  warning      #ffff00   yellow
  mdHeading    #f0c674   warm gold
  mdLink       #81a2be   steel blue
  userMsgBg    #343541   dark blue-gray (user message background)
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass

from pygments.formatters import TerminalTrueColorFormatter
from pygments.lexers import get_lexer_by_name
from pygments.style import Style
from pygments.token import (
    Comment,
    Error,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Token,
)
from pygments.util import ClassNotFound as _PygClassNotFound

from agents.agent import Agent, TextEvent, ToolCallEvent, ToolResultEvent
from ai.providers.factory import get_provider, get_providers
from app.tui.autocomplete import CombinedAutocompleteProvider, SlashCommand
from app.tui.components.box import Box
from app.tui.components.editor import Editor, EditorOptions, EditorTheme, SelectListTheme
from app.tui.components.footer import Footer
from app.tui.components.loader import Loader
from app.tui.components.markdown import Markdown, MarkdownTheme
from app.tui.components.select_list import SelectItem, SelectList
from app.tui.components.select_list import SelectListTheme as SLTheme
from app.tui.components.spacer import Spacer
from app.tui.components.text import Text
from app.tui.terminal import ProcessTerminal
from app.tui.tui import TUI, Container
from state import state

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OSC 133 semantic zone markers (shell integration — mirrors pi-tui)
# ---------------------------------------------------------------------------

_OSC133_ZONE_START = "\x1b]133;A\x07"
_OSC133_ZONE_END   = "\x1b]133;B\x07"
_OSC133_ZONE_FINAL = "\x1b]133;C\x07"

# ---------------------------------------------------------------------------
# Core color helpers — exact hex truecolor, fg-only reset (\x1b[39m)
# Mirrors Theme.fg() / Theme.bg() from theme.js
# ---------------------------------------------------------------------------

def _fg(r: int, g: int, b: int) -> Callable[[str], str]:
    """Return a color function that applies a truecolor fg and resets only fg."""
    code = f"\x1b[38;2;{r};{g};{b}m"
    return lambda s: f"{code}{s}\x1b[39m"

def _bg(r: int, g: int, b: int) -> Callable[[str], str]:
    """Return a color function that applies a truecolor bg and resets only bg."""
    code = f"\x1b[48;2;{r};{g};{b}m"
    return lambda s: f"{code}{s}\x1b[49m"

# -- Foreground palette (dark.json resolved) ---------------------------------
_accent          = _fg(138, 190, 183)   # #8abeb7  sage teal
_border_muted    = _fg( 80,  80,  80)   # #505050  dark gray  → editor border
_muted           = _fg(128, 128, 128)   # #808080  medium gray → descriptions, hr, quotes
_dim             = _fg(102, 102, 102)   # #666666  dim gray   → footer, secondary text
_success         = _fg(181, 189, 104)   # #b5bd68  olive green → code blocks
_error           = _fg(204, 102, 102)   # #cc6666  muted red
_warning         = _fg(255, 255,   0)   # #ffff00  yellow
_heading         = _fg(240, 198, 116)   # #f0c674  warm gold  → md headings
_link            = _fg(129, 162, 190)   # #81a2be  steel blue → md links
_tool_output     = _fg(128, 128, 128)   # #808080  gray → tool result text

# -- Background palette ------------------------------------------------------
_user_msg_bg_fn      = _bg( 52,  53,  65)   # #343541  user message background
_tool_pending_bg_fn  = _bg( 40,  40,  50)   # #282832  tool executing
_tool_success_bg_fn  = _bg( 40,  50,  40)   # #283228  tool succeeded
_tool_error_bg_fn    = _bg( 60,  40,  40)   # #3c2828  tool failed

# -- Text attributes — chalk-compatible resets (NOT \x1b[0m full reset) -----
def _bold(s: str)          -> str: return f"\x1b[1m{s}\x1b[22m"
def _italic(s: str)        -> str: return f"\x1b[3m{s}\x1b[23m"
def _underline(s: str)     -> str: return f"\x1b[4m{s}\x1b[24m"
def _strikethrough(s: str) -> str: return f"\x1b[9m{s}\x1b[29m"

# ---------------------------------------------------------------------------
# Syntax highlighting — custom Pygments style matching dark.json syntax colors
# ---------------------------------------------------------------------------

class _PiDarkStyle(Style):
    """VSCode Dark+-inspired syntax style matching dark.json syntaxXxx colors."""
    background_color = "#1e1e24"
    default_style = ""
    styles = {
        Token:                        "",
        Comment:                      "#6A9955",   # syntaxComment
        Comment.Single:               "#6A9955",
        Comment.Multiline:            "#6A9955",
        Keyword:                      "#569CD6",   # syntaxKeyword
        Keyword.Declaration:          "#569CD6",
        Keyword.Namespace:            "#569CD6",
        Keyword.Type:                 "#4EC9B0",   # syntaxType
        Name.Builtin:                 "#4EC9B0",   # syntaxType
        Name.Class:                   "#4EC9B0",
        Name.Function:                "#DCDCAA",   # syntaxFunction
        Name.Function.Magic:          "#DCDCAA",
        Name.Attribute:               "#9CDCFE",   # syntaxVariable
        Name.Variable:                "#9CDCFE",
        Name.Variable.Instance:       "#9CDCFE",
        Name.Variable.Class:          "#9CDCFE",
        Name.Variable.Global:         "#9CDCFE",
        Name.Namespace:               "#4EC9B0",
        String:                       "#CE9178",   # syntaxString
        String.Doc:                   "#CE9178",
        String.Interpol:              "#CE9178",
        String.Escape:                "#D7BA7D",
        Number:                       "#B5CEA8",   # syntaxNumber
        Number.Integer:               "#B5CEA8",
        Number.Float:                 "#B5CEA8",
        Number.Hex:                   "#B5CEA8",
        Operator:                     "#D4D4D4",   # syntaxOperator
        Operator.Word:                "#569CD6",
        Punctuation:                  "#D4D4D4",   # syntaxPunctuation
        Error:                        "#cc6666",
    }

_pi_dark_formatter = TerminalTrueColorFormatter(style=_PiDarkStyle)


def _highlight_code(code: str, lang: str | None) -> list[str]:
    """Syntax-highlight *code* using the pi-tui dark theme colors.

    Mirrors highlightCode() in theme.js: skips auto-detection when no language
    is given (unreliable), applies theme's mdCodeBlock color as fallback.
    """
    from pygments import highlight as _pyg_highlight
    if not lang:
        return [_success(line) for line in code.split("\n")]
    try:
        lexer = get_lexer_by_name(lang, stripall=True)
    except _PygClassNotFound:
        return [_success(line) for line in code.split("\n")]
    highlighted = _pyg_highlight(code, lexer, _pi_dark_formatter)
    if highlighted.endswith("\n"):
        highlighted = highlighted[:-1]
    return highlighted.split("\n")


# ---------------------------------------------------------------------------
# Themes — all colors from dark.json
# ---------------------------------------------------------------------------

# SelectList: accent for selected items, muted (#808080) for descriptions
_select_list_theme = SLTheme(
    selected_prefix=_accent,        # theme.fg("accent", …)  #8abeb7
    selected_text=_accent,          # theme.fg("accent", …)  #8abeb7
    description=_muted,             # theme.fg("muted", …)   #808080
    scroll_info=_muted,             # theme.fg("muted", …)   #808080
    no_match=_muted,                # theme.fg("muted", …)   #808080
)

_editor_select_theme = SelectListTheme(
    selected_prefix=_accent,
    selected_text=_accent,
    description=_muted,
    scroll_info=_muted,
    no_match=_muted,
)

# Editor: borderMuted (#505050 dark gray)
_editor_theme = EditorTheme(
    border_color=_border_muted,     # theme.fg("borderMuted", …)  #505050
    select_list=_editor_select_theme,
)

# Markdown: exact per-role colors from dark.json
_md_theme = MarkdownTheme(
    heading=_heading,               # mdHeading  #f0c674
    link=_link,                     # mdLink     #81a2be
    link_url=_dim,                  # mdLinkUrl  #666666 (dimGray)
    code=_accent,                   # mdCode     #8abeb7 (accent)
    code_block=_success,            # mdCodeBlock #b5bd68 (green)
    code_block_border=_muted,       # mdCodeBlockBorder #808080
    quote=_muted,                   # mdQuote    #808080
    quote_border=_muted,            # mdQuoteBorder #808080
    hr=_muted,                      # mdHr       #808080
    list_bullet=_accent,            # mdListBullet #8abeb7 (accent)
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
# Tool display helpers — per-tool call/result formatting (mirrors pi-tui)
# ---------------------------------------------------------------------------

BASH_PREVIEW_LINES = 5
READ_PREVIEW_LINES = 10
WRITE_PREVIEW_LINES = 10


def _shorten_path(path: str) -> str:
    """Replace /home/<user>/ prefix with ~/."""
    home = os.path.expanduser("~")
    if path.startswith(home + "/"):
        return "~/" + path[len(home) + 1 :]
    return path


def _format_tool_call_text(tool_name: str, args: dict | str | None) -> str:
    """Format the call header line for a tool invocation."""
    if isinstance(args, str) or args is None:
        return _bold(f"{tool_name} {args or ''}")

    if tool_name == "tool_bash":
        command = args.get("command", "...")
        timeout = args.get("timeout")
        text = _bold(f"$ {command}")
        if timeout:
            text += _muted(f" (timeout {timeout}s)")
        return text

    if tool_name == "tool_read":
        raw_path = args.get("path", "...")
        path_display = _accent(_shorten_path(raw_path)) if raw_path != "..." else _tool_output("...")
        offset = args.get("offset")
        limit = args.get("limit")
        if offset is not None or limit is not None:
            start = offset or 1
            end = f"-{start + limit - 1}" if limit else ""
            path_display += _warning(f":{start}{end}")
        return f"{_bold('read')} {path_display}"

    if tool_name == "tool_edit":
        raw_path = args.get("path", "...")
        path_display = _accent(_shorten_path(raw_path)) if raw_path != "..." else _tool_output("...")
        return f"{_bold('edit')} {path_display}"

    if tool_name == "tool_write":
        raw_path = args.get("path", "...")
        path_display = _accent(_shorten_path(raw_path)) if raw_path != "..." else _tool_output("...")
        return f"{_bold('write')} {path_display}"

    # Fallback for unknown tools
    parts = []
    for k, v in (args if isinstance(args, dict) else {}).items():
        val = str(v)
        if len(val) > 120:
            val = val[:117] + "..."
        parts.append(f"{_dim(k + '=')}{ val}")
    args_str = ", ".join(parts)
    text = _bold(tool_name)
    if args_str:
        text += f"\n{args_str}"
    return text


def _format_tool_result_text(
    tool_name: str,
    args: dict | str | None,
    result: str,
    elapsed_s: float | None,
    is_error: bool,
) -> str | None:
    """Format the result portion for a tool. Returns None if nothing to show."""
    if tool_name == "tool_bash":
        lines = result.split("\n") if result else []
        parts: list[str] = []
        if len(lines) > BASH_PREVIEW_LINES:
            skipped = len(lines) - BASH_PREVIEW_LINES
            parts.append(_muted(f"... ({skipped} earlier lines)"))
            lines = lines[-BASH_PREVIEW_LINES:]
        for line in lines:
            parts.append(_tool_output(line))
        if elapsed_s is not None:
            parts.append(_muted(f"Took {elapsed_s:.1f}s"))
        return "\n".join(parts)

    if tool_name == "tool_read":
        if is_error:
            return _error(result)
        lines = result.split("\n") if result else []
        # Syntax highlight based on file path
        raw_path = args.get("path", "") if isinstance(args, dict) else ""
        highlighted = _highlight_for_path(result, raw_path)
        if len(highlighted) > READ_PREVIEW_LINES:
            remaining = len(highlighted) - READ_PREVIEW_LINES
            display = highlighted[:READ_PREVIEW_LINES]
            display.append(_muted(f"... ({remaining} more lines)"))
            return "\n" + "\n".join(display)
        return "\n" + "\n".join(highlighted)

    if tool_name in ("tool_edit", "tool_write"):
        if is_error:
            return _error(result)
        return None  # success → silent

    # Fallback
    if is_error:
        return _error(result)
    lines = result.split("\n") if result else []
    if len(lines) > 8:
        lines = lines[:8] + [_muted(f"... ({len(result.split(chr(10)))} lines total)")]
    return "\n".join(_tool_output(l) for l in lines)


def _highlight_for_path(code: str, path: str) -> list[str]:
    """Syntax-highlight code based on file extension, falling back to toolOutput color."""
    from pygments import highlight as _pyg_highlight
    from pygments.lexers import get_lexer_for_filename

    if not path:
        return [_tool_output(line) for line in code.split("\n")]
    try:
        lexer = get_lexer_for_filename(path, stripall=True)
    except _PygClassNotFound:
        return [_tool_output(line) for line in code.split("\n")]
    highlighted = _pyg_highlight(code, lexer, _pi_dark_formatter)
    if highlighted.endswith("\n"):
        highlighted = highlighted[:-1]
    return highlighted.split("\n")


@dataclass
class _ToolView:
    """Tracks a single tool invocation's UI state."""
    tool_name: str
    args: dict | str | None
    box: Box


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

    def _setup_ui(self) -> None:
        # Footer — uses dim (#666666) for all text, matching theme.fg("dim", …)
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

        # Editor — borderMuted (#505050) border, accent autocomplete theme
        self._editor = Editor(
            self.tui, _editor_theme,
            EditorOptions(padding_x=0, autocomplete_max_visible=5),
        )
        self._editor.set_autocomplete_provider(autocomplete)
        self._editor.on_submit = self._on_submit

        # Header: accent-colored title (mirrors pi-tui header style)
        self._chat_container.add_child(
            Text(_bold(_accent("Agent 007")) + " — mini mode", padding_x=0, padding_y=0)
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
            elif cmd == "clear":
                if self.agent:
                    self.agent.clear_history()
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
                    help_lines.append(f"  {_accent(f'/{c:<8}')} — {desc}")
                self._add_message(Text("\n".join(help_lines), padding_x=1, padding_y=0))
                self._add_message(Spacer(1))
                return
            else:
                self._add_message(
                    Text(_error(f"Unknown command: {text}"), padding_x=1, padding_y=0)
                )
                self._add_message(Spacer(1))
                return

        # Chat message
        if not self.agent:
            self._add_message(
                Text(_error("❌ Please select a model first (/model)"), padding_x=1, padding_y=0)
            )
            self._add_message(Spacer(1))
            return

        # User message bubble: userMessageBg background + OSC 133 zones
        self._add_message(_UserMessage(text, padding_x=1, padding_y=1, custom_bg_fn=_user_msg_bg_fn))
        self._add_message(Spacer(1))

        asyncio.ensure_future(self._stream_response(text))

    async def _stream_response(self, user_text: str) -> None:
        if not self.agent or self._awaiting_response:
            return
        self._awaiting_response = True

        # Loader: accent spinner, dim message (mirrors BorderedLoader colors)
        loader = Loader(self.tui, _accent, _dim, "Working...")
        self._add_message(loader)

        # Markdown response component (may be replaced after tool calls)
        md: Markdown | None = None
        loader_removed = False

        # Track tool views for bg color transitions
        tool_views: dict[str, _ToolView] = {}
        fallback_tool_views: list[_ToolView] = []

        try:
            def event_handler(event) -> None:
                nonlocal md, loader_removed

                if not loader_removed:
                    loader.stop()
                    self._chat_container.remove_child(loader)
                    loader_removed = True

                if isinstance(event, ToolCallEvent):
                    md = None

                    # Create a Box with pending background
                    box = Box(padding_x=1, padding_y=1, bg_fn=_tool_pending_bg_fn)
                    call_text = _format_tool_call_text(event.tool_name, event.args)
                    box.add_child(Text(call_text, padding_x=0, padding_y=0))

                    tv = _ToolView(
                        tool_name=event.tool_name,
                        args=event.args,
                        box=box,
                    )

                    self._add_message(Spacer(1))
                    self._add_message(box)

                    if event.tool_call_id:
                        tool_views[event.tool_call_id] = tv
                    else:
                        fallback_tool_views.append(tv)
                    self.tui.request_render()

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
                            tv.box.set_bg_fn(_tool_error_bg_fn)
                        else:
                            tv.box.set_bg_fn(_tool_success_bg_fn)

                        # Add result content if applicable
                        result_text = _format_tool_result_text(
                            tv.tool_name, tv.args,
                            event.result, event.elapsed_s, event.is_error,
                        )
                        if result_text is not None:
                            tv.box.add_child(
                                Text(result_text, padding_x=0, padding_y=0)
                            )
                    self.tui.request_render()

                elif isinstance(event, TextEvent):
                    if md is None:
                        md = Markdown("", padding_x=1, padding_y=0, theme=_md_theme)
                        self._add_message(md)
                    md.set_text(event.text)
                    self.tui.request_render()

            await self.agent.stream(user_text, event_handler)

        except Exception as e:
            logger.exception("Error during agent stream")
            if not loader_removed:
                loader.stop()
                self._chat_container.remove_child(loader)
            # Mark any pending tools as errored
            for tv in list(tool_views.values()) + fallback_tool_views:
                tv.box.set_bg_fn(_tool_error_bg_fn)
            err_md = Markdown("", padding_x=1, padding_y=0, theme=_md_theme)
            self._add_message(err_md)
            err_md.set_text(_error(f"❌ {e}"))
            self.tui.request_render()
        finally:
            if not loader_removed:
                loader.stop()
                self._chat_container.remove_child(loader)
            self._awaiting_response = False
            self._add_message(Spacer(1))
            self.tui.request_render()

    async def _cmd_login(self) -> None:
        providers = get_providers()
        if not providers:
            self._add_message(Text(_error("No providers available."), padding_x=1, padding_y=0))
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
                    Text(_success(f"Authenticated with {selected_provider}."), padding_x=1, padding_y=0)
                )
            except Exception as e:
                self._add_message(Text(_error(f"Auth failed: {e}"), padding_x=1, padding_y=0))
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
                Text(_error("No models available. Login first (/login)."), padding_x=1, padding_y=0)
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
                    Text(_success(f"Switched to {model_id} ({provider_name})."), padding_x=1, padding_y=0)
                )
                self._update_footer()
            except Exception as e:
                self._add_message(Text(_error(f"Failed: {e}"), padding_x=1, padding_y=0))
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
