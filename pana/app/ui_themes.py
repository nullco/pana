"""Shared UI theme objects used across commands and the main app.

All theme objects reference ``_theme.*`` wrapper functions rather than raw
colour values, so a call to :func:`apply_theme` propagates immediately to
every already-constructed component.
"""
from __future__ import annotations

from pana.app import theme as _theme
from pana.tui.components.editor import SelectListTheme as EditorSelectListTheme
from pana.tui.components.select_list import SelectListTheme as SLTheme
from pana.tui.components.settings_list import SettingsListTheme

select_list_theme = SLTheme(
    selected_prefix=_theme.accent,
    selected_text=_theme.accent,
    description=_theme.muted,
    scroll_info=_theme.muted,
    no_match=_theme.muted,
)

# Same shape, different type — used inside the Editor's inline popup.
editor_select_theme = EditorSelectListTheme(
    selected_prefix=_theme.accent,
    selected_text=_theme.accent,
    description=_theme.muted,
    scroll_info=_theme.muted,
    no_match=_theme.muted,
)

_settings_theme: SettingsListTheme | None = None


def _make_settings_theme() -> SettingsListTheme:
    return SettingsListTheme(
        label=lambda s, sel: _theme.accent(s) if sel else s,
        value=lambda s, sel: _theme.accent(s) if sel else _theme.muted(s),
        description=_theme.muted,
        cursor=_theme.accent("❯ "),
        hint=_theme.dim,
    )


def get_settings_theme() -> SettingsListTheme:
    """Return the current settings theme, building it on first access."""
    global _settings_theme
    if _settings_theme is None:
        _settings_theme = _make_settings_theme()
    return _settings_theme


def apply_theme(name: str) -> None:
    """Switch the active colour palette and rebuild stateful theme objects."""
    global _settings_theme
    _theme.apply_theme(name)
    _settings_theme = _make_settings_theme()
