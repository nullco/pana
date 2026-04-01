"""Tests for the pana theme system."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pana.tui.theme import (
    PanaTheme,
    _256_to_rgb,
    _parse_hex,
    _resolve_rgb,
    discover_themes,
    load_theme,
    load_theme_file,
    invalidate_cache,
    REQUIRED_COLOR_KEYS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _extract_fg_rgb(color_fn) -> tuple[int, int, int] | None:
    """Call *color_fn* with a sentinel and extract the embedded RGB triple."""
    result = color_fn("X")
    m = re.search(r"\x1b\[38;2;(\d+);(\d+);(\d+)m", result)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


def _extract_bg_rgb(color_fn) -> tuple[int, int, int] | None:
    result = color_fn("X")
    m = re.search(r"\x1b\[48;2;(\d+);(\d+);(\d+)m", result)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


# ---------------------------------------------------------------------------
# Low-level color parsing
# ---------------------------------------------------------------------------


class TestParseHex:
    def test_valid_lowercase(self):
        assert _parse_hex("#8abeb7") == (138, 190, 183)

    def test_valid_uppercase(self):
        assert _parse_hex("#8ABEB7") == (138, 190, 183)

    def test_black(self):
        assert _parse_hex("#000000") == (0, 0, 0)

    def test_white(self):
        assert _parse_hex("#ffffff") == (255, 255, 255)

    def test_invalid_returns_none(self):
        assert _parse_hex("8abeb7") is None   # missing #
        assert _parse_hex("#8abe") is None    # too short
        assert _parse_hex("#gggggg") is None  # invalid hex digits


class Test256ToRgb:
    def test_basic_black(self):
        assert _256_to_rgb(0) == (0, 0, 0)

    def test_basic_white(self):
        assert _256_to_rgb(15) == (255, 255, 255)

    def test_cube_entry(self):
        # index 16 = R=0, G=0, B=0 (first cube entry after basic colors)
        r, g, b = _256_to_rgb(16)
        assert (r, g, b) == (0, 0, 0)

    def test_cube_pure_red(self):
        # index 16 + 36*5 = 196 = R=5, G=0, B=0 → (255, 0, 0)
        r, g, b = _256_to_rgb(196)
        assert r == 255 and g == 0 and b == 0

    def test_grayscale(self):
        # index 232 → darkest gray  (8, 8, 8)
        r, g, b = _256_to_rgb(232)
        assert r == g == b == 8

    def test_grayscale_brightest(self):
        r, g, b = _256_to_rgb(255)
        assert r == g == b == 238


class TestResolveRgb:
    def test_hex(self):
        assert _resolve_rgb("#ff0000", {}) == (255, 0, 0)

    def test_256_color(self):
        result = _resolve_rgb(0, {})
        assert result == (0, 0, 0)

    def test_empty_string_is_default(self):
        assert _resolve_rgb("", {}) is None

    def test_variable_reference(self):
        vars_ = {"myred": "#cc0000"}
        assert _resolve_rgb("myred", vars_) == (0xCC, 0, 0)

    def test_chained_variable(self):
        vars_ = {"a": "b", "b": "#aabbcc"}
        assert _resolve_rgb("a", vars_) == (0xAA, 0xBB, 0xCC)

    def test_cycle_breaks_gracefully(self):
        vars_ = {"a": "b", "b": "a"}
        # Should not raise, just return None after hitting depth limit
        result = _resolve_rgb("a", vars_)
        assert result is None


# ---------------------------------------------------------------------------
# Theme file loading
# ---------------------------------------------------------------------------


class TestLoadThemeFile:
    def _make_minimal_theme(self, tmp_path: Path, **overrides) -> Path:
        """Write a minimal valid theme JSON to *tmp_path* and return the path."""
        colors = {
            "accent": "#8abeb7", "borderMuted": "#505050",
            "muted": "#808080", "dim": "#666666",
            "success": "#b5bd68", "error": "#cc6666", "warning": "#ffff00",
            "mdHeading": "#f0c674", "mdLink": "#81a2be", "mdLinkUrl": "#666666",
            "mdCode": "#8abeb7", "mdCodeBlock": "#b5bd68", "mdCodeBlockBorder": "#808080",
            "mdQuote": "#808080", "mdQuoteBorder": "#808080", "mdHr": "#808080",
            "mdListBullet": "#8abeb7",
            "toolOutput": "#808080", "toolDiffAdded": "#b5bd68",
            "toolDiffRemoved": "#cc6666", "toolDiffContext": "#808080",
            "thinkingText": "#808080",
            "userMessageBg": "#343541", "toolPendingBg": "#282832",
            "toolSuccessBg": "#283228", "toolErrorBg": "#3c2828",
            "syntaxComment": "#6a9955", "syntaxKeyword": "#569cd6",
            "syntaxFunction": "#dcdcaa", "syntaxVariable": "#9cdcfe",
            "syntaxString": "#ce9178", "syntaxNumber": "#b5cea8",
            "syntaxType": "#4ec9b0", "syntaxOperator": "#d4d4d4",
            "syntaxPunctuation": "#d4d4d4",
        }
        colors.update(overrides)
        data = {"name": "test-theme", "colors": colors}
        p = tmp_path / "test-theme.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_loads_valid_theme(self, tmp_path):
        p = self._make_minimal_theme(tmp_path)
        theme = load_theme_file(p)
        assert isinstance(theme, PanaTheme)
        assert theme.name == "test-theme"

    def test_accent_fg_color(self, tmp_path):
        p = self._make_minimal_theme(tmp_path, accent="#ff0000")
        theme = load_theme_file(p)
        rgb = _extract_fg_rgb(theme.accent)
        assert rgb == (255, 0, 0)

    def test_user_message_bg_color(self, tmp_path):
        p = self._make_minimal_theme(tmp_path, userMessageBg="#112233")
        theme = load_theme_file(p)
        rgb = _extract_bg_rgb(theme.user_message_bg)
        assert rgb == (0x11, 0x22, 0x33)

    def test_var_resolution(self, tmp_path):
        data = {
            "name": "vars-theme",
            "vars": {"myblue": "#0000ff"},
            "colors": {k: "#000000" for k in REQUIRED_COLOR_KEYS},
        }
        # Override accent to reference a var
        data["colors"]["accent"] = "myblue"
        p = tmp_path / "vars-theme.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        theme = load_theme_file(p)
        rgb = _extract_fg_rgb(theme.accent)
        assert rgb == (0, 0, 255)

    def test_empty_color_becomes_identity(self, tmp_path):
        data = {
            "name": "default-theme",
            "colors": {k: "#000000" for k in REQUIRED_COLOR_KEYS},
        }
        data["colors"]["accent"] = ""
        p = tmp_path / "default-theme.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        theme = load_theme_file(p)
        # Identity function: output equals input (no ANSI codes)
        assert theme.accent("hello") == "hello"

    def test_256_color_index(self, tmp_path):
        data = {
            "name": "256-theme",
            "colors": {k: "#000000" for k in REQUIRED_COLOR_KEYS},
        }
        data["colors"]["accent"] = 196  # pure red in 256-color
        p = tmp_path / "256-theme.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        theme = load_theme_file(p)
        rgb = _extract_fg_rgb(theme.accent)
        assert rgb == (255, 0, 0)

    def test_missing_key_raises(self, tmp_path):
        data = {"name": "incomplete", "colors": {}}
        p = tmp_path / "incomplete.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError, match="missing required color keys"):
            load_theme_file(p)

    def test_name_falls_back_to_stem(self, tmp_path):
        data = {"colors": {k: "#000000" for k in REQUIRED_COLOR_KEYS}}
        p = tmp_path / "my-fallback.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        theme = load_theme_file(p)
        assert theme.name == "my-fallback"

    def test_syntax_formatter_created(self, tmp_path):
        p = self._make_minimal_theme(tmp_path)
        theme = load_theme_file(p)
        assert theme.syntax_formatter is not None


# ---------------------------------------------------------------------------
# Built-in themes
# ---------------------------------------------------------------------------


class TestBuiltinThemes:
    def test_dark_discovered(self):
        themes = discover_themes()
        assert "dark" in themes

    def test_light_discovered(self):
        themes = discover_themes()
        assert "light" in themes

    def test_load_dark(self):
        invalidate_cache("dark")
        theme = load_theme("dark", use_cache=False)
        assert isinstance(theme, PanaTheme)
        assert theme.name == "dark"

    def test_load_light(self):
        invalidate_cache("light")
        theme = load_theme("light", use_cache=False)
        assert isinstance(theme, PanaTheme)
        assert theme.name == "light"

    def test_dark_accent_is_teal(self):
        invalidate_cache("dark")
        theme = load_theme("dark", use_cache=False)
        rgb = _extract_fg_rgb(theme.accent)
        assert rgb == (0x8A, 0xBE, 0xB7)  # #8abeb7

    def test_dark_error_is_red(self):
        invalidate_cache("dark")
        theme = load_theme("dark", use_cache=False)
        rgb = _extract_fg_rgb(theme.error)
        assert rgb == (0xCC, 0x66, 0x66)  # #cc6666

    def test_dark_user_message_bg(self):
        invalidate_cache("dark")
        theme = load_theme("dark", use_cache=False)
        rgb = _extract_bg_rgb(theme.user_message_bg)
        assert rgb == (0x34, 0x35, 0x41)  # #343541

    def test_light_accent_is_teal(self):
        invalidate_cache("light")
        theme = load_theme("light", use_cache=False)
        rgb = _extract_fg_rgb(theme.accent)
        assert rgb == (0x0E, 0x73, 0x70)  # #0e7370

    def test_light_user_message_bg_is_light(self):
        invalidate_cache("light")
        theme = load_theme("light", use_cache=False)
        rgb = _extract_bg_rgb(theme.user_message_bg)
        # Light background — all channels > 200
        assert all(c > 200 for c in rgb)

    def test_unknown_theme_falls_back_to_dark(self):
        invalidate_cache()
        theme = load_theme("does-not-exist-xyz", use_cache=False)
        assert theme.name == "dark"

    def test_dark_and_light_have_different_accents(self):
        invalidate_cache()
        dark = load_theme("dark", use_cache=False)
        light = load_theme("light", use_cache=False)
        assert _extract_fg_rgb(dark.accent) != _extract_fg_rgb(light.accent)


# ---------------------------------------------------------------------------
# Discover themes
# ---------------------------------------------------------------------------


class TestDiscoverThemes:
    def test_returns_dict(self):
        themes = discover_themes()
        assert isinstance(themes, dict)
        assert len(themes) >= 2  # at least dark + light

    def test_paths_exist(self):
        for name, path in discover_themes().items():
            assert path.exists(), f"Theme path for '{name}' does not exist: {path}"

    def test_user_theme_overrides_builtin(self, tmp_path, monkeypatch):
        """A user theme with the same name as a built-in should shadow it."""
        user_dir = tmp_path / ".pana" / "themes"
        user_dir.mkdir(parents=True)
        custom = {
            "name": "dark",
            "colors": {k: "#112233" for k in REQUIRED_COLOR_KEYS},
        }
        (user_dir / "dark.json").write_text(json.dumps(custom), encoding="utf-8")

        # Patch Path.home() to point at tmp_path
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        themes = discover_themes()
        assert themes["dark"] == user_dir / "dark.json"

    def test_project_theme_discovered(self, tmp_path, monkeypatch):
        """A project-local theme in .pana/themes/ is discovered."""
        proj_dir = tmp_path / ".pana" / "themes"
        proj_dir.mkdir(parents=True)
        custom = {
            "name": "project-custom",
            "colors": {k: "#aabbcc" for k in REQUIRED_COLOR_KEYS},
        }
        (proj_dir / "project-custom.json").write_text(json.dumps(custom), encoding="utf-8")

        monkeypatch.chdir(tmp_path)
        themes = discover_themes()
        assert "project-custom" in themes


# ---------------------------------------------------------------------------
# Color function output format
# ---------------------------------------------------------------------------


class TestColorFunctionOutput:
    def test_fg_contains_content(self):
        invalidate_cache("dark")
        theme = load_theme("dark", use_cache=False)
        result = theme.accent("hello")
        assert "hello" in result

    def test_fg_resets_fg_only(self):
        invalidate_cache("dark")
        theme = load_theme("dark", use_cache=False)
        result = theme.accent("X")
        # Should end with fg-only reset, not full reset
        assert "\x1b[39m" in result
        assert "\x1b[0m" not in result

    def test_bg_resets_bg_only(self):
        invalidate_cache("dark")
        theme = load_theme("dark", use_cache=False)
        result = theme.user_message_bg("X")
        assert "\x1b[49m" in result
        assert "\x1b[0m" not in result

    def test_stripped_text_unchanged(self):
        invalidate_cache("dark")
        theme = load_theme("dark", use_cache=False)
        # After stripping ANSI codes the payload should be intact
        assert _strip_ansi(theme.muted("test string")) == "test string"


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


class TestCache:
    def test_cached_result_is_same_object(self):
        invalidate_cache("dark")
        t1 = load_theme("dark")
        t2 = load_theme("dark")
        assert t1 is t2

    def test_use_cache_false_returns_new_object(self):
        invalidate_cache("dark")
        t1 = load_theme("dark")
        t2 = load_theme("dark", use_cache=False)
        assert t1 is not t2

    def test_invalidate_named_entry(self):
        _ = load_theme("dark")
        invalidate_cache("dark")
        from pana.tui.theme import _cache
        assert "dark" not in _cache

    def test_invalidate_all(self):
        _ = load_theme("dark")
        _ = load_theme("light")
        invalidate_cache()
        from pana.tui.theme import _cache
        assert len(_cache) == 0
