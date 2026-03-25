"""Regression tests for regional-indicator / emoji width handling.

Ported from upstream regression-regional-indicator-width.test.ts.
Exercises ``visible_width`` and ``_grapheme_width`` from :mod:`app.tui.utils`
for emoji, regional-indicator, ZWJ-sequence, and CJK edge cases.
"""
from __future__ import annotations

from pana.tui.utils import _grapheme_width, visible_width

# -- Regional indicator pairs (flags) --------------------------------------

def test_regional_indicator_pair_width_2():
    """Flag emoji (regional indicator pair) should have width 2."""
    assert visible_width("🇨🇳") == 2


def test_single_regional_indicator_width_2():
    """Isolated regional indicator should have width 2."""
    assert visible_width("🇨") == 2


def test_us_flag_width_2():
    assert visible_width("🇺🇸") == 2


def test_mixed_text_with_flag():
    """Text with embedded flag emoji."""
    assert visible_width("Hello 🇺🇸 World") == 14  # 5 + 1 + 2 + 1 + 5


def test_multiple_flags():
    """Multiple flag pairs."""
    assert visible_width("🇺🇸🇬🇧") == 4  # 2 + 2


# -- Regular emoji ----------------------------------------------------------

def test_regular_emoji_width_2():
    """Regular emoji should have width 2."""
    assert visible_width("😀") == 2


def test_emoji_with_vs16():
    """Emoji with VS16 presentation selector should have width 2."""
    assert visible_width("☺️") == 2  # ☺ + VS16


# -- ZWJ sequences ----------------------------------------------------------

def test_zwj_sequence():
    """ZWJ emoji sequence should have width 2."""
    assert visible_width("👨‍👩‍👧") == 2


# -- CJK characters ---------------------------------------------------------

def test_cjk_character():
    """CJK characters should have width 2."""
    assert visible_width("中") == 2


def test_mixed_cjk_and_ascii():
    """Mix of CJK and ASCII."""
    assert visible_width("A中B") == 4  # 1 + 2 + 1


# -- _grapheme_width low-level checks ---------------------------------------

def test_grapheme_width_regional_pair():
    assert _grapheme_width("🇺🇸") == 2


def test_grapheme_width_regular_emoji():
    assert _grapheme_width("😀") == 2


def test_grapheme_width_cjk():
    assert _grapheme_width("中") == 2
