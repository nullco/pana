"""Theme configuration for the chat UI."""
from __future__ import annotations

from pana.app import theme as _theme
from pana.app import ui_themes
from pana.tui.components.editor import EditorTheme
from pana.tui.components.markdown import MarkdownTheme

editor_theme = EditorTheme(
    border_color=_theme.border_muted,
    select_list=ui_themes.editor_select_theme,
)

md_theme = MarkdownTheme(
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
