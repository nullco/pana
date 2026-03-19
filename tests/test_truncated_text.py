"""Tests for the TruncatedText component."""

from __future__ import annotations

from app.tui.components.truncated_text import TruncatedText
from app.tui.utils import visible_width


def test_pads_output_to_match_width() -> None:
    lines = TruncatedText("Hello world", padding_x=1, padding_y=0).render(50)
    assert len(lines) == 1
    assert visible_width(lines[0]) == 50


def test_vertical_padding_lines() -> None:
    lines = TruncatedText("Hello", padding_x=0, padding_y=2).render(40)
    assert len(lines) == 5
    for line in lines:
        assert visible_width(line) == 40


def test_truncates_long_text_with_ellipsis() -> None:
    lines = TruncatedText("A" * 80, padding_x=1, padding_y=0).render(30)
    assert len(lines) == 1
    assert visible_width(lines[0]) == 30
    assert "..." in lines[0]


def test_preserves_ansi_codes_and_pads() -> None:
    lines = TruncatedText(
        "\x1b[31mHello\x1b[0m \x1b[34mworld\x1b[0m",
        padding_x=1,
        padding_y=0,
    ).render(40)
    assert len(lines) == 1
    assert visible_width(lines[0]) == 40
    assert "\x1b[" in lines[0]


def test_truncates_styled_text_with_reset_before_ellipsis() -> None:
    lines = TruncatedText(
        "\x1b[31m" + "A" * 50 + "\x1b[0m",
        padding_x=1,
        padding_y=0,
    ).render(20)
    assert visible_width(lines[0]) == 20
    assert "..." in lines[0]


def test_handles_text_that_fits_exactly() -> None:
    lines = TruncatedText("Hello world", padding_x=1, padding_y=0).render(30)
    assert len(lines) == 1
    assert visible_width(lines[0]) == 30
    assert "..." not in lines[0]


def test_handles_empty_text() -> None:
    lines = TruncatedText("", padding_x=1, padding_y=0).render(30)
    assert len(lines) == 1
    assert visible_width(lines[0]) == 30


def test_stops_at_newline_shows_first_line_only() -> None:
    lines = TruncatedText(
        "First line\nSecond line\nThird line",
        padding_x=1,
        padding_y=0,
    ).render(40)
    assert len(lines) == 1
    assert visible_width(lines[0]) == 40
    assert "First line" in lines[0]
    assert "Second line" not in lines[0]
    assert "Third line" not in lines[0]


def test_truncates_first_line_with_newlines() -> None:
    lines = TruncatedText(
        "very long first line that should be truncated here\nSecond line",
        padding_x=1,
        padding_y=0,
    ).render(25)
    assert len(lines) == 1
    assert visible_width(lines[0]) == 25
    assert "..." in lines[0]
    assert "Second line" not in lines[0]
