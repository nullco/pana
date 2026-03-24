"""Tests for the Markdown rendering component, ported from markdown.test.ts."""
from __future__ import annotations

import re

from app.tui.components.markdown import DefaultTextStyle, Markdown, MarkdownTheme
from app.tui.utils import visible_width

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _identity(s: str) -> str:
    return s


def _bold(s: str) -> str:
    return f"\x1b[1m{s}\x1b[22m"


def _italic(s: str) -> str:
    return f"\x1b[3m{s}\x1b[23m"


def _underline(s: str) -> str:
    return f"\x1b[4m{s}\x1b[24m"


def _cyan(s: str) -> str:
    return f"\x1b[36m{s}\x1b[39m"


def _yellow(s: str) -> str:
    return f"\x1b[33m{s}\x1b[39m"


def _blue(s: str) -> str:
    return f"\x1b[34m{s}\x1b[39m"


def _dim(s: str) -> str:
    return f"\x1b[2m{s}\x1b[22m"


def _green(s: str) -> str:
    return f"\x1b[32m{s}\x1b[39m"


def _gray(s: str) -> str:
    return f"\x1b[90m{s}\x1b[39m"


def _strikethrough(s: str) -> str:
    return f"\x1b[9m{s}\x1b[29m"


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _heading(s: str) -> str:
    return _bold(_cyan(s))


_THEME = MarkdownTheme(
    heading=_cyan,
    link=_blue,
    link_url=_dim,
    code=_yellow,
    code_block=_green,
    code_block_border=_dim,
    quote=_italic,
    quote_border=_dim,
    hr=_dim,
    list_bullet=_cyan,
    bold=_bold,
    italic=_italic,
    strikethrough=_strikethrough,
    underline=_underline,
)


def _render(
    text: str,
    width: int = 80,
    padding_x: int = 0,
    padding_y: int = 0,
    style: DefaultTextStyle | None = None,
) -> list[str]:
    md = Markdown(text, padding_x, padding_y, _THEME, style)
    return md.render(width)


def _plain_lines(lines: list[str]) -> list[str]:
    return [_strip_ansi(line) for line in lines]


# ===================================================================
# Nested lists
# ===================================================================


def test_simple_nested_list() -> None:
    lines = _render("- Item 1\n  - Nested 1.1\n  - Nested 1.2\n- Item 2")
    plain = _plain_lines(lines)
    joined = "\n".join(plain)
    assert "- Item 1" in joined
    assert "- Nested 1.1" in joined
    assert "- Nested 1.2" in joined
    assert "- Item 2" in joined


def test_deeply_nested_list() -> None:
    text = "- Level 1\n  - Level 2\n    - Level 3\n      - Level 4"
    lines = _render(text)
    plain = _plain_lines(lines)
    joined = "\n".join(plain)
    assert "Level 1" in joined
    assert "Level 2" in joined
    assert "Level 3" in joined
    assert "Level 4" in joined


def test_ordered_nested_list() -> None:
    text = "1. First\n   1. Nested first\n   2. Nested second\n2. Second"
    lines = _render(text)
    plain = _plain_lines(lines)
    joined = "\n".join(plain)
    assert "1." in joined
    assert "2." in joined
    assert "Nested first" in joined
    assert "Nested second" in joined


def test_mixed_ordered_unordered() -> None:
    text = "1. Ordered\n   - Bullet nested\n2. Ordered again"
    lines = _render(text)
    plain = _plain_lines(lines)
    joined = "\n".join(plain)
    assert "1." in joined
    assert "- Bullet nested" in joined or "Bullet nested" in joined
    assert "2." in joined


def test_numbering_with_code_blocks() -> None:
    text = "1. Item one\n\n```\ncode block\n```\n\n2. Item two\n\n```\nanother block\n```\n\n3. Item three"
    lines = _render(text)
    plain = _plain_lines(lines)
    digit_lines = [l for l in plain if l.strip() and re.match(r"\d", l.strip())]
    assert len(digit_lines) == 3


# ===================================================================
# Tables
# ===================================================================


def test_simple_table() -> None:
    text = "| Name | Age |\n| --- | --- |\n| Alice | 30 |\n| Bob | 25 |"
    lines = _render(text, width=80)
    joined = "\n".join(lines)
    assert "Name" in joined
    assert "Age" in joined
    assert "Alice" in joined
    assert "Bob" in joined
    assert "│" in joined
    assert "─" in joined


def test_row_dividers() -> None:
    text = "| Name | Age |\n| --- | --- |\n| Alice | 30 |\n| Bob | 25 |"
    lines = _render(text, width=80)
    cross_lines = [l for l in lines if "┼" in l]
    assert len(cross_lines) == 2


def test_min_column_width_longest_word() -> None:
    text = "| Header |\n| --- |\n| superlongword |"
    lines = _render(text, width=32)
    plain = _plain_lines(lines)
    joined = "\n".join(plain)
    assert "superlongword" in joined


def test_table_alignment() -> None:
    text = "| Left | Center | Right |\n| :--- | :---: | ---: |\n| L | C | R |"
    lines = _render(text, width=80)
    joined = "\n".join(lines)
    assert "Left" in joined
    assert "Center" in joined
    assert "Right" in joined


def test_varying_column_widths() -> None:
    text = "| Short | A much longer header column |\n| --- | --- |\n| x | Some cell text here |"
    lines = _render(text, width=80)
    joined = "\n".join(lines)
    assert "Short" in joined
    assert "A much longer header column" in joined


def test_wrap_table_cells() -> None:
    text = "| Col1 | Col2 | Col3 |\n| --- | --- | --- |\n| Short | Medium text | Longer cell content here |"
    lines = _render(text, width=50)
    for line in lines:
        assert visible_width(line) <= 50


def test_wrap_long_cell_content() -> None:
    text = "| Header |\n| --- |\n| This is a very long cell that should wrap across multiple lines in the table |"
    lines = _render(text, width=25)
    plain = _plain_lines(lines)
    # Data rows are lines between the header separator (┼) and the bottom border (└)
    data_rows = [l for l in plain if l.strip() and "│" in l and "─" not in l]
    # Exclude the header row (contains "Header")
    data_rows = [l for l in data_rows if "Header" not in l]
    assert len(data_rows) > 2


def test_wrap_long_unbroken_token() -> None:
    text = "| URL |\n| --- |\n| https://example.com/very/long/path/that/goes/on |"
    lines = _render(text, width=30)
    for line in lines:
        assert visible_width(line) <= 30
    table_lines = [l for l in lines if "│" in l and "─" not in l]
    for tl in table_lines:
        assert tl.count("│") >= 2


def test_wrap_styled_inline_code_in_cell() -> None:
    text = "| Code |\n| --- |\n| `some_long_inline_code_here` |"
    lines = _render(text, width=20)
    joined = "".join(lines)
    assert "\x1b[33m" in joined
    for line in lines:
        assert visible_width(line) <= 20


def test_extremely_narrow_table() -> None:
    text = "| A | B | C |\n| --- | --- | --- |\n| 1 | 2 | 3 |"
    lines = _render(text, width=15)
    assert len(lines) > 0
    for line in lines:
        assert visible_width(line) <= 15


def test_table_fits_naturally() -> None:
    text = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    lines = _render(text, width=80)
    plain = _plain_lines(lines)
    header_line = [l for l in plain if "A" in l and "B" in l]
    assert len(header_line) > 0
    assert "│" in header_line[0]
    sep_lines = [l for l in plain if "├" in l and "┼" in l]
    assert len(sep_lines) >= 1


def test_table_respects_padding_x() -> None:
    text = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    lines = _render(text, width=40, padding_x=2)
    for line in lines:
        assert visible_width(line) <= 40
    table_rows = [l for l in lines if "│" in l and "─" not in l]
    for row in table_rows:
        assert row.startswith("  ")


def test_no_trailing_blank_after_table() -> None:
    text = "| X |\n| --- |\n| Y |"
    lines = _render(text)
    plain = _plain_lines(lines)
    # Find last non-empty line
    last_nonempty = ""
    for l in reversed(plain):
        if l.strip():
            last_nonempty = l
            break
    assert last_nonempty != ""


# ===================================================================
# Spacing after code blocks
# ===================================================================


def test_one_blank_line_between_code_block_and_paragraph() -> None:
    text = "hello world\n\n```js\ncode\n```\n\nagain, hello world"
    lines = _render(text)
    plain = _plain_lines(lines)
    # Find the closing ``` line
    close_idx = None
    for i, l in enumerate(plain):
        if l.strip() == "```" and i > 0:
            close_idx = i
    assert close_idx is not None
    # Count empty lines between close and next non-empty
    blanks = 0
    for l in plain[close_idx + 1 :]:
        if l.strip() == "":
            blanks += 1
        else:
            break
    assert blanks == 1


def test_normalize_code_block_spacing() -> None:
    variant_a = "text\n\n```\ncode\n```\n\ntext"
    variant_b = "text\n```\ncode\n```\ntext"
    lines_a = _plain_lines(_render(variant_a))
    lines_b = _plain_lines(_render(variant_b))
    # Both should produce the same stripped-down sequence
    seq_a = [l.strip() for l in lines_a]
    seq_b = [l.strip() for l in lines_b]
    assert seq_a == seq_b


def test_no_trailing_blank_after_code_block() -> None:
    for text in ["```\ncode\n```", "hello\n\n```\ncode\n```"]:
        lines = _render(text)
        plain = _plain_lines(lines)
        last = ""
        for l in reversed(plain):
            if l.strip():
                last = l
                break
        assert last != ""


# ===================================================================
# Spacing after dividers
# ===================================================================


def test_one_blank_line_after_divider() -> None:
    text = "---\n\nSome text"
    lines = _render(text)
    plain = _plain_lines(lines)
    divider_idx = None
    for i, l in enumerate(plain):
        if "─" in l:
            divider_idx = i
            break
    assert divider_idx is not None
    blanks = 0
    for l in plain[divider_idx + 1 :]:
        if l.strip() == "":
            blanks += 1
        else:
            break
    assert blanks == 1


def test_no_trailing_blank_after_divider() -> None:
    lines = _render("---")
    plain = _plain_lines(lines)
    last = ""
    for l in reversed(plain):
        if l.strip():
            last = l
            break
    assert last != ""


# ===================================================================
# Spacing after headings
# ===================================================================


def test_one_blank_line_after_heading() -> None:
    text = "# Hello\n\nSome text"
    lines = _render(text)
    plain = _plain_lines(lines)
    heading_idx = None
    for i, l in enumerate(plain):
        if "Hello" in l:
            heading_idx = i
            break
    assert heading_idx is not None
    blanks = 0
    for l in plain[heading_idx + 1 :]:
        if l.strip() == "":
            blanks += 1
        else:
            break
    assert blanks == 1


def test_no_trailing_blank_after_heading() -> None:
    lines = _render("# Hello")
    plain = _plain_lines(lines)
    last = ""
    for l in reversed(plain):
        if l.strip():
            last = l
            break
    assert last != ""


# ===================================================================
# Spacing after blockquotes
# ===================================================================


def test_one_blank_line_after_blockquote() -> None:
    text = "> This is a quote\n\nSome text"
    lines = _render(text)
    plain = _plain_lines(lines)
    quote_idx = None
    for i, l in enumerate(plain):
        if "This is a quote" in l:
            quote_idx = i
            break
    assert quote_idx is not None
    blanks = 0
    for l in plain[quote_idx + 1 :]:
        if l.strip() == "":
            blanks += 1
        else:
            break
    assert blanks == 1


def test_no_trailing_blank_after_blockquote() -> None:
    lines = _render("> This is a quote")
    plain = _plain_lines(lines)
    last = ""
    for l in reversed(plain):
        if l.strip():
            last = l
            break
    assert last != ""


# ===================================================================
# Blockquotes with multiline content
# ===================================================================


def test_lazy_continuation_blockquote() -> None:
    def _magenta(s):
        return f"\x1b[35m{s}\x1b[39m"
    style = DefaultTextStyle(color=_magenta)
    lines = _render(">Foo\nbar", style=style)
    border_lines = [l for l in lines if _strip_ansi(l).startswith("│ ")]
    assert len(border_lines) >= 1
    for bl in border_lines:
        assert "\x1b[3m" in bl  # italic from quote theme
        assert "\x1b[35m" not in bl  # magenta should NOT appear inside quote


def test_explicit_multiline_blockquote() -> None:
    style = DefaultTextStyle(color=lambda s: f"\x1b[36m{s}\x1b[39m")
    lines = _render(">Foo\n>bar", style=style)
    border_lines = [l for l in lines if _strip_ansi(l).startswith("│ ")]
    assert len(border_lines) >= 1
    for bl in border_lines:
        assert "\x1b[3m" in bl  # italic
        assert "\x1b[36m" not in bl  # cyan default color should NOT appear


def test_list_inside_blockquote() -> None:
    text = "> 1. bla bla\n> - nested bullet"
    lines = _render(text)
    plain = _plain_lines(lines)
    quoted_lines = [l for l in plain if l.startswith("│ ")]
    joined = "\n".join(quoted_lines)
    assert "1." in joined
    assert "-" in joined


def test_wrap_long_blockquote_with_border() -> None:
    text = "> This is a very long blockquote line that should be wrapped across multiple lines"
    lines = _render(text, width=30)
    plain = _plain_lines(lines)
    content_lines = [l for l in plain if l.startswith("│ ")]
    assert len(content_lines) > 1
    for cl in content_lines:
        assert cl.startswith("│ ")


def test_styled_blockquote_wrapping() -> None:
    style = DefaultTextStyle(color=lambda s: f"\x1b[33m{s}\x1b[39m", italic=True)
    text = "> This is styled text that wraps"
    lines = _render(text, width=25, style=style)
    plain = _plain_lines(lines)
    content_lines = [l for l in plain if l.startswith("│ ")]
    assert len(content_lines) >= 1
    joined = "".join(lines)
    assert "\x1b[3m" in joined  # italic
    assert "\x1b[33m" not in joined  # yellow should NOT leak into quote


def test_inline_formatting_in_blockquote() -> None:
    text = "> Quote with **bold** and `code`"
    lines = _render(text)
    plain = _plain_lines(lines)
    quoted = [l for l in plain if l.startswith("│ ")]
    joined_plain = " ".join(quoted)
    assert "bold" in joined_plain
    assert "code" in joined_plain
    joined_raw = "".join(lines)
    assert "\x1b[1m" in joined_raw  # bold
    assert "\x1b[33m" in joined_raw  # yellow code
    assert "\x1b[3m" in joined_raw  # italic from quote


# ===================================================================
# Links
# ===================================================================


def test_no_duplicate_url_autolinked_email() -> None:
    text = "Contact user@example.com for help"
    lines = _render(text)
    plain = _plain_lines(lines)
    joined = " ".join(plain)
    assert "user@example.com" in joined
    assert "mailto:" not in joined


def test_no_duplicate_url_bare_urls() -> None:
    text = "Visit https://example.com for more"
    lines = _render(text)
    plain = _plain_lines(lines)
    joined = " ".join(plain)
    assert joined.count("https://example.com") == 1


def test_show_url_for_markdown_links() -> None:
    text = "[click here](https://example.com)"
    lines = _render(text)
    plain = _plain_lines(lines)
    joined = " ".join(plain)
    assert "click here" in joined
    assert "(https://example.com)" in joined


def test_show_url_for_mailto_links() -> None:
    text = "[Email me](mailto:test@example.com)"
    lines = _render(text)
    plain = _plain_lines(lines)
    joined = " ".join(plain)
    assert "Email me" in joined
    assert "(mailto:test@example.com)" in joined


# ===================================================================
# HTML-like tags
# ===================================================================


def test_html_tags_as_text() -> None:
    text = "Text with <thinking>hidden content</thinking> more text"
    lines = _render(text)
    plain = _plain_lines(lines)
    joined = " ".join(plain)
    assert "hidden content" in joined or "<thinking>" in joined


def test_html_in_code_blocks() -> None:
    text = "```html\n<div>Some HTML</div>\n```"
    lines = _render(text)
    plain = _plain_lines(lines)
    joined = " ".join(plain)
    assert "<div>" in joined
    assert "</div>" in joined


# ===================================================================
# Pre-styled text
# ===================================================================


def test_preserve_gray_italic_after_inline_code() -> None:
    md = Markdown(
        "Text with `inline code` and more text",
        1,
        0,
        _THEME,
        DefaultTextStyle(color=_gray, italic=True),
    )
    lines = md.render(80)
    joined = "".join(lines)
    plain_joined = " ".join(_plain_lines(lines))
    assert "inline code" in plain_joined
    assert "\x1b[90m" in joined  # gray
    assert "\x1b[3m" in joined  # italic
    assert "\x1b[33m" in joined  # yellow code


def test_preserve_gray_italic_after_bold() -> None:
    md = Markdown(
        "Text with **bold text** and more",
        1,
        0,
        _THEME,
        DefaultTextStyle(color=_gray, italic=True),
    )
    lines = md.render(80)
    joined = "".join(lines)
    plain_joined = " ".join(_plain_lines(lines))
    assert "bold text" in plain_joined
    assert "\x1b[90m" in joined  # gray
    assert "\x1b[3m" in joined  # italic
    assert "\x1b[1m" in joined  # bold
