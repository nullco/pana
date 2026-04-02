"""Theme loading and resolution for pana.

Themes are JSON files with this structure::

    {
        "name": "my-theme",
        "vars": {
            "teal": "#8abeb7",
            "gray": "#808080"
        },
        "colors": {
            "accent": "teal",
            "muted":  "gray",
            "userMessageBg": "#343541",
            ...
        }
    }

Discovery order (later entries override earlier ones):
  1. Built-in themes shipped with pana  (``pana/themes/*.json``)
  2. User themes                        (``~/.pana/themes/*.json``)
  3. Project themes                     (``.pana/themes/*.json``)

Color values can be:
  - ``"#rrggbb"``  — 24-bit hex
  - ``242``        — xterm 256-color index
  - ``"varname"``  — reference to an entry in ``vars``
  - ``""``         — terminal default (no ANSI code applied)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pygments.formatters import TerminalTrueColorFormatter
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

from pana.tui.ansi import ANSI

ColorFn = Callable[[str], str]

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$")


def _parse_hex(value: str) -> tuple[int, int, int] | None:
    m = _HEX_RE.match(value)
    if m:
        return int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16)
    return None


def _256_to_rgb(n: int) -> tuple[int, int, int]:
    """Convert an xterm 256-color index to an approximate (r, g, b) triple."""
    if n < 16:
        _basic = [
            (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
            (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
            (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
            (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
        ]
        return _basic[n]
    if n < 232:
        n -= 16
        b = n % 6
        g = (n // 6) % 6
        r = n // 36
        def _c(x: int) -> int:
            return 0 if x == 0 else 55 + x * 40
        return _c(r), _c(g), _c(b)
    v = 8 + (n - 232) * 10
    return v, v, v


def _resolve_rgb(
    value: str | int,
    vars_dict: dict[str, str | int],
    _depth: int = 0,
) -> tuple[int, int, int] | None:
    """Resolve a color value to (r, g, b) or None (terminal default).

    Handles hex strings, 256-color integers, variable references, and empty
    strings (which mean "use the terminal's default foreground/background").
    Cycles in ``vars`` are broken after 16 levels of recursion.
    """
    if _depth > 16:
        return None
    if isinstance(value, int):
        return _256_to_rgb(max(0, min(255, value)))
    if not value:
        return None  # "" → terminal default
    if value in vars_dict:
        return _resolve_rgb(vars_dict[value], vars_dict, _depth + 1)
    if value.startswith("#"):
        return _parse_hex(value)
    return None


# Identity function used when a color resolves to the terminal default.
_IDENTITY: ColorFn = lambda s: s  # noqa: E731


def _make_fg(rgb: tuple[int, int, int]) -> ColorFn:
    r, g, b = rgb
    code = ANSI.fg_rgb(r, g, b)
    return lambda s: f"{code}{s}{ANSI.FG_RESET}"


def _make_bg(rgb: tuple[int, int, int]) -> ColorFn:
    r, g, b = rgb
    code = ANSI.bg_rgb(r, g, b)
    return lambda s: f"{code}{s}{ANSI.BG_RESET}"


def _color_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


@dataclass
class PanaTheme:
    """Resolved theme: every field is a ready-to-call ANSI color function.

    Foreground functions wrap their argument with an ANSI truecolor fg code
    and reset only the fg channel (``\\x1b[39m``).  Background functions do
    the same for the bg channel (``\\x1b[49m``).  Fields whose JSON color is
    ``""`` use ``_IDENTITY`` (no-op — inherits the terminal default).
    """

    name: str

    accent: ColorFn
    border_muted: ColorFn
    muted: ColorFn
    dim: ColorFn
    success: ColorFn
    error: ColorFn
    warning: ColorFn

    md_heading: ColorFn
    md_link: ColorFn
    md_link_url: ColorFn
    md_code: ColorFn
    md_code_block: ColorFn
    md_code_block_border: ColorFn
    md_quote: ColorFn
    md_quote_border: ColorFn
    md_hr: ColorFn
    md_list_bullet: ColorFn

    tool_output: ColorFn
    tool_diff_added: ColorFn
    tool_diff_removed: ColorFn
    tool_diff_context: ColorFn
    thinking_text: ColorFn

    user_message_bg: ColorFn
    tool_pending_bg: ColorFn
    tool_success_bg: ColorFn
    tool_error_bg: ColorFn

    syntax_formatter: TerminalTrueColorFormatter


def _make_syntax_formatter(
    syntax: dict[str, str],
    bg_color: str = "#1e1e24",
) -> TerminalTrueColorFormatter:
    """Build a Pygments ``TerminalTrueColorFormatter`` from resolved hex colors.

    ``syntax`` must map the token-name strings (``"syntaxComment"`` etc.) to
    6-digit hex colors (``"#rrggbb"``).  Missing keys fall back to neutral
    defaults.
    """
    comment = syntax.get("syntaxComment", "#808080")
    keyword = syntax.get("syntaxKeyword", "#569cd6")
    func    = syntax.get("syntaxFunction", "#dcdcaa")
    var_    = syntax.get("syntaxVariable", "#9cdcfe")
    string  = syntax.get("syntaxString", "#ce9178")
    number  = syntax.get("syntaxNumber", "#b5cea8")
    type_   = syntax.get("syntaxType", "#4ec9b0")
    op      = syntax.get("syntaxOperator", "#d4d4d4")
    punct   = syntax.get("syntaxPunctuation", "#d4d4d4")
    err     = syntax.get("error", "#cc6666")

    styles: dict = {
        Token:                    "",
        Comment:                  comment,
        Comment.Single:           comment,
        Comment.Multiline:        comment,
        Keyword:                  keyword,
        Keyword.Declaration:      keyword,
        Keyword.Namespace:        keyword,
        Keyword.Type:             type_,
        Name.Builtin:             type_,
        Name.Class:               type_,
        Name.Function:            func,
        Name.Function.Magic:      func,  # type: ignore[attr-defined]
        Name.Attribute:           var_,
        Name.Variable:            var_,
        Name.Variable.Instance:   var_,  # type: ignore[attr-defined]
        Name.Variable.Class:      var_,  # type: ignore[attr-defined]
        Name.Variable.Global:     var_,  # type: ignore[attr-defined]
        Name.Namespace:           type_,
        String:                   string,
        String.Doc:               string,  # type: ignore[attr-defined]
        String.Interpol:          string,  # type: ignore[attr-defined]
        String.Escape:            string,  # type: ignore[attr-defined]
        Number:                   number,
        Number.Integer:           number,  # type: ignore[attr-defined]
        Number.Float:             number,  # type: ignore[attr-defined]
        Number.Hex:               number,  # type: ignore[attr-defined]
        Operator:                 op,
        Operator.Word:            keyword,
        Punctuation:              punct,
        Error:                    err,
    }

    style_cls = type(
        "_PanaSyntaxStyle",
        (Style,),
        {"background_color": bg_color, "default_style": "", "styles": styles},
    )
    return TerminalTrueColorFormatter(style=style_cls)


#: All color token keys that a theme JSON file must supply.
REQUIRED_COLOR_KEYS: tuple[str, ...] = (
    "accent", "borderMuted", "muted", "dim", "success", "error", "warning",
    "mdHeading", "mdLink", "mdLinkUrl", "mdCode", "mdCodeBlock", "mdCodeBlockBorder",
    "mdQuote", "mdQuoteBorder", "mdHr", "mdListBullet",
    "toolOutput", "toolDiffAdded", "toolDiffRemoved", "toolDiffContext", "thinkingText",
    "userMessageBg", "toolPendingBg", "toolSuccessBg", "toolErrorBg",
    "syntaxComment", "syntaxKeyword", "syntaxFunction", "syntaxVariable",
    "syntaxString", "syntaxNumber", "syntaxType", "syntaxOperator", "syntaxPunctuation",
)

_SYNTAX_KEYS = (
    "syntaxComment", "syntaxKeyword", "syntaxFunction", "syntaxVariable",
    "syntaxString", "syntaxNumber", "syntaxType", "syntaxOperator", "syntaxPunctuation",
)


def load_theme_file(path: Path) -> PanaTheme:
    """Parse a theme JSON file and return a fully-resolved :class:`PanaTheme`.

    Raises ``ValueError`` for missing required keys, ``json.JSONDecodeError``
    for malformed JSON, and ``OSError`` if the file cannot be read.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    name: str = data.get("name", path.stem)
    vars_dict: dict[str, str | int] = data.get("vars", {})
    raw: dict[str, str | int] = data.get("colors", {})

    missing = [k for k in REQUIRED_COLOR_KEYS if k not in raw]
    if missing:
        raise ValueError(
            f"Theme '{name}' is missing required color keys: {', '.join(missing)}"
        )

    def fg(key: str) -> ColorFn:
        rgb = _resolve_rgb(raw[key], vars_dict)
        return _make_fg(rgb) if rgb is not None else _IDENTITY

    def bg(key: str) -> ColorFn:
        rgb = _resolve_rgb(raw[key], vars_dict)
        return _make_bg(rgb) if rgb is not None else _IDENTITY

    def to_hex(key: str) -> str:
        rgb = _resolve_rgb(raw[key], vars_dict)
        return _color_to_hex(rgb) if rgb is not None else ""

    syntax_hex = {k: to_hex(k) for k in _SYNTAX_KEYS}
    syntax_hex["error"] = to_hex("error")

    return PanaTheme(
        name=name,
        accent=fg("accent"),
        border_muted=fg("borderMuted"),
        muted=fg("muted"),
        dim=fg("dim"),
        success=fg("success"),
        error=fg("error"),
        warning=fg("warning"),
        md_heading=fg("mdHeading"),
        md_link=fg("mdLink"),
        md_link_url=fg("mdLinkUrl"),
        md_code=fg("mdCode"),
        md_code_block=fg("mdCodeBlock"),
        md_code_block_border=fg("mdCodeBlockBorder"),
        md_quote=fg("mdQuote"),
        md_quote_border=fg("mdQuoteBorder"),
        md_hr=fg("mdHr"),
        md_list_bullet=fg("mdListBullet"),
        tool_output=fg("toolOutput"),
        tool_diff_added=fg("toolDiffAdded"),
        tool_diff_removed=fg("toolDiffRemoved"),
        tool_diff_context=fg("toolDiffContext"),
        thinking_text=fg("thinkingText"),
        user_message_bg=bg("userMessageBg"),
        tool_pending_bg=bg("toolPendingBg"),
        tool_success_bg=bg("toolSuccessBg"),
        tool_error_bg=bg("toolErrorBg"),
        syntax_formatter=_make_syntax_formatter(syntax_hex),
    )


def _builtin_themes_dir() -> Path:
    # pana/tui/theme.py → pana/ → themes/
    return Path(__file__).parent.parent / "themes"


def discover_themes() -> dict[str, Path]:
    """Return a ``{name: path}`` mapping of all discoverable themes.

    Search order (later entries shadow earlier ones):

    1. Built-in themes shipped inside the ``pana`` package.
    2. User-global themes at ``~/.pana/themes/*.json``.
    3. Project-local themes at ``.pana/themes/*.json`` (cwd-relative).
    """
    found: dict[str, Path] = {}

    def _scan(directory: Path) -> None:
        if not directory.is_dir():
            return
        for p in sorted(directory.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                theme_name = data.get("name", p.stem)
            except Exception:
                theme_name = p.stem
            found[theme_name] = p

    _scan(_builtin_themes_dir())
    _scan(Path.home() / ".pana" / "themes")
    _scan(Path(".pana") / "themes")

    return found


_cache: dict[str, PanaTheme] = {}


def load_theme(name: str, *, use_cache: bool = True) -> PanaTheme:
    """Load a theme by name, falling back to ``"dark"`` if not found.

    The resolved theme is cached; pass ``use_cache=False`` to force a reload
    (useful after editing a custom theme file).
    """
    if use_cache and name in _cache:
        return _cache[name]

    themes = discover_themes()
    if name not in themes:
        fallback = "dark" if "dark" in themes else (next(iter(themes), None))
        if fallback is None:
            raise RuntimeError("No themes found — the pana/themes/ directory is missing.")
        name = fallback

    theme = load_theme_file(themes[name])
    _cache[name] = theme
    return theme


def invalidate_cache(name: str | None = None) -> None:
    """Clear the theme cache.  Pass a name to evict only that entry."""
    if name is None:
        _cache.clear()
    else:
        _cache.pop(name, None)
