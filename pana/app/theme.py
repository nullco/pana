"""Active-theme state and color helper functions.

All functions delegate to ``_current_theme`` so a single ``apply_theme()``
call updates every subsequent render without rebuilding any component.
"""
from __future__ import annotations

from pana.tui.ansi import ANSI
from pana.tui.theme import PanaTheme, load_theme

_current_theme: PanaTheme = load_theme("dark")


def apply_theme(name: str) -> None:
    """Switch the active theme.  Safe to call at any time."""
    global _current_theme
    from pana.tui.theme import invalidate_cache
    invalidate_cache(name)
    _current_theme = load_theme(name, use_cache=False)


def get_current_theme() -> PanaTheme:
    return _current_theme


def accent(s: str)        -> str: return _current_theme.accent(s)
def border_muted(s: str)  -> str: return _current_theme.border_muted(s)
def muted(s: str)         -> str: return _current_theme.muted(s)
def dim(s: str)           -> str: return _current_theme.dim(s)
def success(s: str)       -> str: return _current_theme.success(s)
def error(s: str)         -> str: return _current_theme.error(s)
def warning(s: str)       -> str: return _current_theme.warning(s)
def heading(s: str)       -> str: return _current_theme.md_heading(s)
def link(s: str)          -> str: return _current_theme.md_link(s)
def tool_output(s: str)   -> str: return _current_theme.tool_output(s)
def diff_added(s: str)    -> str: return _current_theme.tool_diff_added(s)
def diff_removed(s: str)  -> str: return _current_theme.tool_diff_removed(s)
def diff_context(s: str)  -> str: return _current_theme.tool_diff_context(s)
def thinking_text(s: str) -> str: return _current_theme.thinking_text(s)

def user_msg_bg(s: str)     -> str: return _current_theme.user_message_bg(s)
def tool_pending_bg(s: str) -> str: return _current_theme.tool_pending_bg(s)
def tool_success_bg(s: str) -> str: return _current_theme.tool_success_bg(s)
def tool_error_bg(s: str)   -> str: return _current_theme.tool_error_bg(s)

# Text attributes — theme-independent ANSI codes
def bold(s: str)          -> str: return f"{ANSI.BOLD_ON}{s}{ANSI.BOLD_OFF}"
def italic(s: str)        -> str: return f"{ANSI.ITALIC_ON}{s}{ANSI.ITALIC_OFF}"
def underline(s: str)     -> str: return f"{ANSI.UNDERLINE_ON}{s}{ANSI.UNDERLINE_OFF}"
def strikethrough(s: str) -> str: return f"{ANSI.STRIKETHROUGH_ON}{s}{ANSI.STRIKETHROUGH_OFF}"
def inverse(s: str)       -> str: return f"{ANSI.INVERSE_ON}{s}{ANSI.INVERSE_OFF}"


def highlight_code(code: str, lang: str | None) -> list[str]:
    """Syntax-highlight *code* by language name."""
    from pygments import highlight as _pyg_highlight
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound

    if not lang:
        return [success(line) for line in code.split("\n")]
    try:
        lexer = get_lexer_by_name(lang, stripall=True)
    except ClassNotFound:
        return [success(line) for line in code.split("\n")]
    highlighted = _pyg_highlight(code, lexer, _current_theme.syntax_formatter)
    if highlighted.endswith("\n"):
        highlighted = highlighted[:-1]
    return highlighted.split("\n")


def highlight_for_path(code: str, path: str) -> list[str]:
    """Syntax-highlight *code* by file extension."""
    from pygments import highlight as _pyg_highlight
    from pygments.lexers import get_lexer_for_filename
    from pygments.util import ClassNotFound

    if not path:
        return [tool_output(line) for line in code.split("\n")]
    try:
        lexer = get_lexer_for_filename(path, stripall=True)
    except ClassNotFound:
        return [tool_output(line) for line in code.split("\n")]
    highlighted = _pyg_highlight(code, lexer, _current_theme.syntax_formatter)
    if highlighted.endswith("\n"):
        highlighted = highlighted[:-1]
    return highlighted.split("\n")
