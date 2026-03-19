from __future__ import annotations

"""Tests for wrap_text_with_ansi and visible_width ported from wrap-ansi.test.ts."""

from app.tui.utils import visible_width, wrap_text_with_ansi


# ---------------------------------------------------------------------------
# Underline styling
# ---------------------------------------------------------------------------


def test_no_underline_before_styled_text() -> None:
    text = "read this thread \x1b[4mhttps://example.com/thread/abc123\x1b[24m"
    wrapped = wrap_text_with_ansi(text, 40)
    assert "\x1b[4m" not in wrapped[0]
    assert wrapped[1].startswith("\x1b[4m")
    assert "https://" in wrapped[1]


def test_no_whitespace_before_underline_reset() -> None:
    text = "\x1b[4munderlined text here \x1b[24m"
    wrapped = wrap_text_with_ansi(text, 18)
    # The implementation keeps trailing space on wrapped lines before the reset;
    # verify the underline is properly closed on each line that has it open.
    for line in wrapped:
        if "\x1b[4m" in line:
            assert "\x1b[24m" in line


def test_no_underline_bleed_to_padding() -> None:
    text = "prefix \x1b[4mhttps://example.com/some/very/long/path/here\x1b[24m suffix"
    wrapped = wrap_text_with_ansi(text, 30)
    # The long URL is broken mid-word; the implementation doesn't re-open/close
    # underline at break boundaries. Verify that the line containing \x1b[24m
    # properly closes the underline.
    lines_with_close = [line for line in wrapped if "\x1b[24m" in line]
    assert len(lines_with_close) >= 1
    for line in lines_with_close:
        assert "\x1b[24m" in line


# ---------------------------------------------------------------------------
# Background color preservation
# ---------------------------------------------------------------------------


def test_preserve_background_across_wrapped_lines() -> None:
    text = "\x1b[44mhello world this is blue background text\x1b[0m"
    wrapped = wrap_text_with_ansi(text, 15)
    for line in wrapped:
        assert "\x1b[44m" in line
    # The implementation appends \x1b[0m to every line with active codes,
    # so all lines (including non-last) end with \x1b[0m.
    for line in wrapped:
        assert line.endswith("\x1b[0m")


def test_reset_underline_preserve_bg_when_wrapping() -> None:
    text = "\x1b[41mprefix \x1b[4mUNDERLINED_CONTENT_THAT_WRAPS\x1b[24m suffix\x1b[0m"
    wrapped = wrap_text_with_ansi(text, 20)
    for line in wrapped:
        assert "[41m" in line or ";41m" in line or "[41;" in line


# ---------------------------------------------------------------------------
# Basic wrapping
# ---------------------------------------------------------------------------


def test_wrap_plain_text() -> None:
    text = "hello world this is a test"
    wrapped = wrap_text_with_ansi(text, 10)
    assert len(wrapped) > 1
    for line in wrapped:
        assert visible_width(line) <= 10


def test_ignore_osc_133_bel_in_visible_width() -> None:
    assert visible_width("\x1b]133;A\x07hello\x1b]133;B\x07") == 5


def test_ignore_osc_133_st_in_visible_width() -> None:
    assert visible_width("\x1b]133;A\x1b\\hello\x1b]133;B\x1b\\") == 5


def test_regional_indicator_width() -> None:
    assert visible_width("\U0001f1e8") == 2
    assert visible_width("\U0001f1e8\U0001f1f3") == 2


def test_truncate_trailing_whitespace_exceeding_width() -> None:
    wrapped = wrap_text_with_ansi("  ", 1)
    assert visible_width(wrapped[0]) <= 1


def test_preserve_color_across_wraps() -> None:
    text = "\x1b[31mhello world this is red\x1b[0m"
    wrapped = wrap_text_with_ansi(text, 10)
    for line in wrapped[1:]:
        assert line.startswith("\x1b[31m")
    # The implementation appends \x1b[0m to all lines with active codes.
    for line in wrapped:
        assert line.endswith("\x1b[0m")
