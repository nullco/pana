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
import re
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
from pana.tui.tui import TUI, Container

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
_diff_added      = _fg(181, 189, 104)   # #b5bd68  green (vars.green) → diff added lines
_diff_removed    = _fg(204, 102, 102)   # #cc6666  red   (vars.red)   → diff removed lines
_diff_context    = _fg(128, 128, 128)   # #808080  gray  (vars.gray)  → diff context lines
_thinking_text   = _fg(128, 128, 128)   # #808080  gray  (thinkingText) → thinking traces

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
def _inverse(s: str)       -> str: return f"\x1b[7m{s}\x1b[27m"

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
# @file reference expansion
# ---------------------------------------------------------------------------

# Matches @"quoted path" or @unquoted_path — strips the @ so the LLM sees bare paths
_AT_FILE_RE = re.compile(r'@"([^"]+)"|@(\S+)')


def _strip_at_prefixes(text: str) -> str:
    """Strip ``@`` prefixes from file references so the LLM sees bare paths."""
    return _AT_FILE_RE.sub(lambda m: m.group(1) or m.group(2), text)


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

# SettingsList: accent for selected, muted for descriptions, dim for hints
_settings_theme = SettingsListTheme(
    label=lambda s, sel: _accent(s) if sel else s,
    value=lambda s, sel: _accent(s) if sel else _muted(s),
    description=_muted,
    cursor=_accent("❯ "),
    hint=_dim,
)

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

COMMANDS: dict[str, str] = {
    "login": "Authenticate with a provider",
    "model": "Select a model",
    "settings": "Configure thinking level, display options",
    "new": "Start a new session",
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


def _render_diff(diff_string: str) -> str:
    """Render a pi-style diff string with ANSI colors.

    Parses lines of the form ``+NNN content``, ``-NNN content``, `` NNN content``
    and ``     ...`` and applies green/red/dim colors respectively.

    When there is exactly one removed + one added line in sequence (a single-line
    modification), intra-line word-level diff highlighting is applied using
    inverse video on the changed segments.
    """
    import difflib as _difflib

    lines = diff_string.split("\n")
    result: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            result.append("")
            i += 1
            continue

        # Ellipsis (skipped lines)
        stripped = line.strip()
        if stripped == "...":
            result.append(_diff_context(line))
            i += 1
            continue

        prefix = line[0] if line else " "

        if prefix == "-":
            # Check for a single removed+added pair → intra-line highlight
            if (
                i + 1 < len(lines)
                and lines[i + 1]
                and lines[i + 1][0] == "+"
                and (i + 2 >= len(lines) or not lines[i + 2] or lines[i + 2][0] != "+")
            ):
                # Also verify no more consecutive removes before this
                old_line = lines[i]
                new_line = lines[i + 1]
                # Extract the content portion after the line-number field
                # Format: "- NNNN content" or "+  NNN content"
                import re as _re

                old_m = _re.match(r"^([+-]\s*\d+\s)", old_line)
                new_m = _re.match(r"^([+-]\s*\d+\s)", new_line)
                if old_m and new_m:
                    old_prefix_str = old_m.group(1)
                    new_prefix_str = new_m.group(1)
                    old_content = old_line[old_m.end():]
                    new_content = new_line[new_m.end():]

                    # Word-level diff
                    word_diff = list(
                        _difflib.ndiff(
                            old_content.split(), new_content.split()
                        )
                    )
                    old_parts: list[str] = []
                    new_parts: list[str] = []
                    for wd in word_diff:
                        if wd.startswith("- "):
                            old_parts.append(_inverse(wd[2:]))
                        elif wd.startswith("+ "):
                            new_parts.append(_inverse(wd[2:]))
                        elif wd.startswith("  "):
                            old_parts.append(wd[2:])
                            new_parts.append(wd[2:])
                        # skip "? " hint lines

                    result.append(
                        _diff_removed(old_prefix_str) + _diff_removed(" ".join(old_parts))
                    )
                    result.append(
                        _diff_added(new_prefix_str) + _diff_added(" ".join(new_parts))
                    )
                    i += 2
                    continue

            result.append(_diff_removed(line))
        elif prefix == "+":
            result.append(_diff_added(line))
        else:
            result.append(_diff_context(line))
        i += 1

    return "\n".join(result)



def _format_tool_call_text(tool_name: str, args: dict | str | None) -> str:
    """Format the call header line for a tool invocation.

    ``args`` may be ``None`` when called for an early ToolCallEvent whose
    arguments haven't finished streaming yet; each tool branch handles that
    gracefully by displaying ``...`` placeholders.
    """
    if isinstance(args, str):
        return _bold(f"{tool_name} {args}")

    # args is None or a dict from here on — tool branches handle both.

    if tool_name == "tool_bash":
        command = args.get("command", "...") if args else "..."
        timeout = args.get("timeout") if args else None
        text = _bold(f"$ {command}")
        if timeout:
            text += _muted(f" (timeout {timeout}s)")
        return text

    if tool_name == "tool_read":
        raw_path = args.get("path", "...") if args else "..."
        path_display = _accent(_shorten_path(raw_path)) if raw_path != "..." else _muted("...")
        if args:
            offset = args.get("offset")
            limit = args.get("limit")
            if offset is not None or limit is not None:
                start = offset or 1
                end = f"-{start + limit - 1}" if limit else ""
                path_display += _warning(f":{start}{end}")
        return f"{_bold('read')} {path_display}"

    if tool_name == "tool_edit":
        raw_path = args.get("path", "...") if args else "..."
        path_display = _accent(_shorten_path(raw_path)) if raw_path != "..." else _muted("...")
        return f"{_bold('edit')} {path_display}"

    if tool_name == "tool_write":
        raw_path = args.get("path", "...") if args else "..."
        path_display = _accent(_shorten_path(raw_path)) if raw_path != "..." else _muted("...")
        text = f"{_bold('write')} {path_display}"
        content = args.get("content", "") if args else ""
        if content:
            # Split first so we know the true line count without running
            # Pygments over the entire file — only highlight what we display.
            all_lines = content.split("\n")
            while all_lines and all_lines[-1] == "":
                all_lines.pop()
            total_lines = len(all_lines)
            preview_source = "\n".join(all_lines[:WRITE_PREVIEW_LINES])
            highlighted = _highlight_for_path(
                preview_source, raw_path if raw_path != "..." else ""
            )
            remaining = total_lines - WRITE_PREVIEW_LINES
            text += "\n\n" + "\n".join(highlighted)
            if remaining > 0:
                text += "\n" + _muted(f"... ({remaining} more lines, {total_lines} total)")
        return text

    # Fallback for unknown tools
    if not args:
        return _bold(tool_name)
    parts = []
    for k, v in args.items():
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
        output_block = "\n".join(parts)
        sections = ["\n" + output_block]
        if elapsed_s is not None:
            sections.append("\n\n" + _muted(f"Took {elapsed_s:.1f}s"))
        return "".join(sections)

    if tool_name == "tool_read":
        if is_error:
            return "\n" + _error(result)
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
            return "\n" + _error(result)
        return None  # success → silent

    # Fallback
    if is_error:
        return "\n" + _error(result)
    lines = result.split("\n") if result else []
    if len(lines) > 8:
        lines = lines[:8] + [_muted(f"... ({len(result.split(chr(10)))} lines total)")]
    return "\n" + "\n".join(_tool_output(l) for l in lines)


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
    call_text_component: Text  # first child — updated by ToolCallUpdateEvent
    diff_preview: str | None = None  # cached diff shown in renderCall (edit tool)


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
        self._editor.on_action = self._on_action

        # Header: accent-colored title (mirrors pi-tui header style)
        self._chat_container.add_child(
            Text(_bold(_accent("pana")) + " " + _muted(f"v{_version}"), padding_x=0, padding_y=0)
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
                Text(_muted("No model selected"), padding_x=1, padding_y=0),
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
            Text(_muted(f"Thinking level: {next_level}"), padding_x=1, padding_y=0),
        )
        self.tui.request_render()

    def _toggle_thinking_block_visibility(self) -> None:
        self._hide_thinking_block = not self._hide_thinking_block
        state.set("hide_thinking_block", self._hide_thinking_block)
        label = "hidden" if self._hide_thinking_block else "visible"
        self._add_message(
            Text(_muted(f"Thinking blocks: {label}"), padding_x=1, padding_y=0),
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
                self._add_message(Text(_dim("✓ New session started"), padding_x=1, padding_y=0))
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

        # User message bubble — shown immediately even when draining so the
        # user gets instant visual feedback that the message was received.
        self._add_message(Spacer(1))
        self._add_message(_UserMessage(text, padding_x=1, padding_y=1, custom_bg_fn=_user_msg_bg_fn))

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
        tool_views: dict[str, _ToolView] = {}
        fallback_tool_views: list[_ToolView] = []

        # Markdown / thinking components — defined here so on_abort can see them
        md: Markdown | None = None
        thinking_md: Markdown | None = None
        thinking_placeholder: Text | None = None

        # Loader: accent spinner, dim message (mirrors BorderedLoader colors)
        loader = CancellableLoader(self.tui, _accent, _dim, "Working...")

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
                tv.box.set_bg_fn(_tool_error_bg_fn)

            # Remove loader and show the aborted notice
            loader.stop()
            try:
                self._chat_container.remove_child(loader)
            except Exception:
                pass
            self._add_message(Spacer(1))
            self._add_message(Text(_error("Operation aborted"), padding_x=1, padding_y=0))

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
                            _italic(_thinking_text("Thinking...")),
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
                                color=_thinking_text, italic=True
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
                box = Box(padding_x=1, padding_y=1, bg_fn=_tool_pending_bg_fn)
                call_text = _format_tool_call_text(event.tool_name, event.args)
                call_text_component = Text(call_text, padding_x=0, padding_y=0)
                box.add_child(call_text_component)

                tv = _ToolView(
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
                    call_text = _format_tool_call_text(event.tool_name, event.args)

                    # For tool_edit: compute diff preview when args are
                    # complete and append it to the call text (like pi-mono
                    # renderCall).  Store on tv so renderResult can skip it.
                    if (
                        event.tool_name == "tool_edit"
                        and isinstance(event.args, dict)
                        and event.args.get("old_text")
                        and event.args.get("new_text")
                        and event.args.get("path")
                    ):
                        from pana.agents.tools import compute_edit_diff

                        diff_str = compute_edit_diff(
                            event.args["path"],
                            event.args["old_text"],
                            event.args["new_text"],
                        )
                        if diff_str:
                            tv.diff_preview = diff_str
                            call_text += "\n\n" + _render_diff(diff_str)

                    tv.call_text_component.set_text(call_text)

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
                tv.box.set_bg_fn(_tool_error_bg_fn)
            self._add_message(Spacer(1))
            self._add_message(Text(_error("Operation aborted"), padding_x=1, padding_y=0))
            raise

        except Exception as e:
            logger.exception("Error during agent stream")
            if not cancel_event.is_set():
                for tv in list(tool_views.values()) + fallback_tool_views:
                    tv.box.set_bg_fn(_tool_error_bg_fn)
                err_md = Markdown("", padding_x=1, padding_y=0, theme=_md_theme)
                self._add_message(err_md)
                err_md.set_text(_error(f"❌ {e}"))
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
                    thinking_level = state.get("thinking_level", "medium")
                    self.agent = Agent(model, thinking_level=thinking_level)
                state.set("provider", provider_name)
                state.set("model", model_id)
                self._add_message(
                    Text(_success(f"Switched to {model_id} ({provider_name})."), padding_x=1, padding_y=0)
                )
                self._update_footer()
            except Exception as e:
                self._add_message(Text(_error(f"Failed: {e}"), padding_x=1, padding_y=0))
            self._add_message(Spacer(1))

    async def _cmd_settings(self) -> None:
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
