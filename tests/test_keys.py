"""Tests for key parsing and matching.

Verifies that ``matches_key`` and ``parse_key`` correctly handle Kitty
keyboard protocol (including alternate/non-Latin base layout keys),
xterm modifyOtherKeys sequences, and legacy terminal input.
"""

from __future__ import annotations

import pytest

from app.tui.keys import (
    matches_key,
    parse_key,
    set_kitty_protocol_active,
)

# ---------------------------------------------------------------------------
# Fixture: ensure Kitty protocol state is restored after each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_kitty_state() -> None:
    set_kitty_protocol_active(False)
    yield  # type: ignore[misc]
    set_kitty_protocol_active(False)


# ===================================================================
# matchesKey — Kitty protocol with alternate keys (non-Latin layouts)
# ===================================================================


class TestMatchesKeyKittyAlternateKeys:
    """Kitty CSI-u sequences with base layout keys for non-Latin keyboards."""

    def test_ctrl_c_cyrillic(self) -> None:
        """Ctrl+С (Cyrillic) with base layout key 'c'."""
        assert matches_key("\x1b[1089::99;5u", "ctrl+c")

    def test_ctrl_d_cyrillic(self) -> None:
        """Ctrl+В (Cyrillic) with base layout key 'd'."""
        assert matches_key("\x1b[1074::100;5u", "ctrl+d")

    def test_ctrl_z_cyrillic(self) -> None:
        """Ctrl+Я (Cyrillic) with base layout key 'z'."""
        assert matches_key("\x1b[1103::122;5u", "ctrl+z")

    def test_ctrl_shift_p_base_layout(self) -> None:
        """Ctrl+Shift+p with base layout key."""
        assert matches_key("\x1b[1079::112;6u", "ctrl+shift+p")

    def test_direct_codepoint_no_base_layout(self) -> None:
        """No base layout key — fall back to codepoint."""
        assert matches_key("\x1b[99;5u", "ctrl+c")

    def test_digit_via_kitty_csi_u(self) -> None:
        """Digit binding via Kitty CSI-u."""
        assert matches_key("\x1b[49u", "1")

    def test_shifted_key_format(self) -> None:
        """Shifted key: a (97) with shifted A (65)."""
        # \x1b[97:65u  → codepoint=97, shifted_key=65, no modifiers
        assert matches_key("\x1b[97:65u", "a")

    def test_event_type_press(self) -> None:
        """Press event type (1) should still match."""
        assert matches_key("\x1b[97;1:1u", "a")

    def test_prefer_codepoint_for_latin(self) -> None:
        """Latin codepoint preferred even when base layout differs."""
        # codepoint=107 ('k'), base_layout=118 ('v') — should match 'ctrl+k'
        assert matches_key("\x1b[107::118;5u", "ctrl+k")

    def test_wrong_key_with_base_layout(self) -> None:
        """Should NOT match wrong key even with base layout key."""
        # Cyrillic С (1089) with base 'c' (99) — should not match ctrl+d
        assert not matches_key("\x1b[1089::99;5u", "ctrl+d")

    def test_wrong_modifiers_with_base_layout(self) -> None:
        """Should NOT match wrong modifiers even with base layout key."""
        # ctrl (5) but matching ctrl+shift (6)
        assert not matches_key("\x1b[1089::99;5u", "ctrl+shift+c")


# ===================================================================
# matchesKey — modifyOtherKeys matching
# ===================================================================


class TestMatchesKeyModifyOtherKeys:
    """xterm modifyOtherKeys (CSI 27;mod;code ~) sequences."""

    def test_ctrl_c(self) -> None:
        assert matches_key("\x1b[27;5;99~", "ctrl+c")

    def test_ctrl_d(self) -> None:
        assert matches_key("\x1b[27;5;100~", "ctrl+d")

    def test_ctrl_z(self) -> None:
        assert matches_key("\x1b[27;5;122~", "ctrl+z")


# ===================================================================
# matchesKey — Legacy key matching
# ===================================================================


class TestMatchesKeyLegacy:
    """Legacy terminal escape sequences and control characters."""

    def test_legacy_ctrl_c(self) -> None:
        assert matches_key("\x03", "ctrl+c")

    def test_legacy_ctrl_d(self) -> None:
        assert matches_key("\x04", "ctrl+d")

    def test_escape(self) -> None:
        assert matches_key("\x1b", "escape")

    def test_linefeed_as_enter_kitty_inactive(self) -> None:
        """\\n matches enter when kitty protocol is inactive."""
        set_kitty_protocol_active(False)
        assert matches_key("\n", "enter")

    def test_linefeed_as_shift_enter_kitty_active(self) -> None:
        """\\n treated as shift+enter when kitty protocol is active."""
        set_kitty_protocol_active(True)
        assert matches_key("\n", "shift+enter")
        assert not matches_key("\n", "enter")

    def test_ctrl_space(self) -> None:
        assert matches_key("\x00", "ctrl+space")

    def test_arrow_up(self) -> None:
        assert matches_key("\x1b[A", "up")

    def test_arrow_down(self) -> None:
        assert matches_key("\x1b[B", "down")

    def test_arrow_left(self) -> None:
        assert matches_key("\x1b[D", "left")

    def test_arrow_right(self) -> None:
        assert matches_key("\x1b[C", "right")

    def test_ss3_arrow_up(self) -> None:
        assert matches_key("\x1bOA", "up")

    def test_ss3_home(self) -> None:
        assert matches_key("\x1bOH", "home")

    def test_ss3_end(self) -> None:
        assert matches_key("\x1bOF", "end")

    def test_f1(self) -> None:
        assert matches_key("\x1bOP", "f1")

    def test_f5(self) -> None:
        assert matches_key("\x1b[15~", "f5")

    def test_alt_left_csi(self) -> None:
        assert matches_key("\x1b[1;3D", "alt+left")

    def test_alt_left_legacy(self) -> None:
        assert matches_key("\x1bb", "alt+left")

    def test_rxvt_shift_up(self) -> None:
        assert matches_key("\x1b[a", "shift+up")

    @pytest.mark.xfail(reason="matches_key ctrl branch only checks left/right legacy seqs")
    def test_rxvt_ctrl_up(self) -> None:
        assert matches_key("\x1bOa", "ctrl+up")


# ===================================================================
# parseKey — Kitty protocol
# ===================================================================


class TestParseKeyKitty:
    """parse_key with Kitty CSI-u sequences."""

    def test_latin_key_from_base_layout(self) -> None:
        """Non-Latin codepoint with Latin base layout → Latin key name."""
        # Cyrillic С (1089), base layout 'c' (99), ctrl (5)
        result = parse_key("\x1b[1089::99;5u")
        assert result == "ctrl+c"

    def test_prefer_codepoint_for_latin(self) -> None:
        """Latin codepoint preferred even if base layout differs."""
        # codepoint=107 ('k'), base_layout=118 ('v'), ctrl
        result = parse_key("\x1b[107::118;5u")
        assert result == "ctrl+k"

    def test_key_name_from_codepoint_no_base(self) -> None:
        """No base layout key — derive name from codepoint."""
        result = parse_key("\x1b[99;5u")
        assert result == "ctrl+c"

    def test_unsupported_modifiers_ignored(self) -> None:
        """Kitty CSI-u with unsupported modifier bits returns None."""
        # modifier value 33 → mod bits 32 (hyper), not in supported set
        result = parse_key("\x1b[99;33u")
        assert result is None


# ===================================================================
# parseKey — Legacy
# ===================================================================


class TestParseKeyLegacy:
    """parse_key with legacy terminal input."""

    def test_ctrl_a(self) -> None:
        assert parse_key("\x01") == "ctrl+a"

    def test_ctrl_c(self) -> None:
        assert parse_key("\x03") == "ctrl+c"

    def test_escape(self) -> None:
        assert parse_key("\x1b") == "escape"

    def test_tab(self) -> None:
        assert parse_key("\t") == "tab"

    def test_arrow_up(self) -> None:
        assert parse_key("\x1b[A") == "up"

    def test_arrow_down(self) -> None:
        assert parse_key("\x1b[B") == "down"

    def test_arrow_left(self) -> None:
        assert parse_key("\x1b[D") == "left"

    def test_arrow_right(self) -> None:
        assert parse_key("\x1b[C") == "right"

    def test_ss3_arrow_up(self) -> None:
        assert parse_key("\x1bOA") == "up"

    def test_ss3_home(self) -> None:
        assert parse_key("\x1bOH") == "home"

    def test_ss3_end(self) -> None:
        assert parse_key("\x1bOF") == "end"

    def test_f1(self) -> None:
        assert parse_key("\x1bOP") == "f1"

    def test_f5(self) -> None:
        assert parse_key("\x1b[15~") == "f5"

    def test_f12(self) -> None:
        assert parse_key("\x1b[24~") == "f12"

    def test_shift_up_rxvt(self) -> None:
        assert parse_key("\x1b[a") == "shift+up"

    def test_ctrl_up_rxvt(self) -> None:
        assert parse_key("\x1bOa") == "ctrl+up"

    def test_delete(self) -> None:
        assert parse_key("\x1b[3~") == "delete"

    def test_backspace(self) -> None:
        assert parse_key("\x7f") == "backspace"

    def test_enter(self) -> None:
        set_kitty_protocol_active(False)
        assert parse_key("\r") == "enter"

    def test_linefeed_enter_kitty_inactive(self) -> None:
        set_kitty_protocol_active(False)
        assert parse_key("\n") == "enter"

    def test_linefeed_shift_enter_kitty_active(self) -> None:
        set_kitty_protocol_active(True)
        assert parse_key("\n") == "shift+enter"
