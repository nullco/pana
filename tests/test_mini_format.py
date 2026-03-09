"""Tests for app.tui.mini formatting functions."""

import asyncio
import re
import sys
from unittest.mock import MagicMock, patch

from app.tui.mini import _format_code, _format_markdown, _format_plain, _stream_response

_ANSI_RE = re.compile(r"\033\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _ends_with_reset(text: str) -> bool:
    """Check that the text ends with a full ANSI reset so terminal state doesn't leak."""
    return text.rstrip("\n").endswith("\033[0m")


# -- _format_plain ------------------------------------------------------------


class TestFormatPlain:
    def test_plain_text_unchanged(self):
        assert _strip_ansi(_format_plain("hello world")) == "hello world"

    def test_bold(self):
        result = _format_plain("**bold**")
        assert "bold" in _strip_ansi(result)
        assert "\033[1m" in result

    def test_inline_code(self):
        result = _format_plain("use `foo` here")
        assert _strip_ansi(result) == "use foo here"
        assert "\033[36m" in result

    def test_bold_with_inline_code(self):
        result = _format_plain("**bold `code` still bold**")
        stripped = _strip_ansi(result)
        assert "bold" in stripped
        assert "code" in stripped
        assert "still bold" in stripped

    def test_triple_backticks_not_matched_as_inline(self):
        result = _format_plain("see ```example``` above")
        stripped = _strip_ansi(result)
        assert "```example```" in stripped

    def test_reset_handled_by_format_markdown(self):
        assert _ends_with_reset(_format_markdown("**bold** and `code`"))
        assert _ends_with_reset(_format_markdown("just plain text"))

    def test_multiline_bold(self):
        result = _format_plain("**bold\ntext**")
        stripped = _strip_ansi(result)
        assert "bold\ntext" in stripped


# -- _format_code -------------------------------------------------------------


class TestFormatCode:

    def test_unknown_lang_falls_back(self):
        result = _format_code("hello\n", "nonexistent_lang_xyz")
        assert "hello" in _strip_ansi(result)

    def test_empty_lang_guesses(self):
        result = _format_code("x = 1\n", "")
        assert "x = 1" in _strip_ansi(result)


# -- _format_markdown ---------------------------------------------------------


class TestFormatMarkdown:
    def test_plain_only(self):
        result = _format_markdown("hello world")
        assert _strip_ansi(result) == "hello world"
        assert _ends_with_reset(result)

    def test_code_block(self):
        md = "```python\nx = 1\n```"
        result = _format_markdown(md)
        assert "x = 1" in _strip_ansi(result)
        assert _ends_with_reset(result)

    def test_text_before_code_block(self):
        md = "Here is code:\n```python\nx = 1\n```"
        result = _format_markdown(md)
        stripped = _strip_ansi(result)
        assert "Here is code:" in stripped
        assert "x = 1" in stripped
        assert _ends_with_reset(result)

    def test_text_after_code_block(self):
        md = "```python\nx = 1\n```\nDone."
        result = _format_markdown(md)
        stripped = _strip_ansi(result)
        assert "x = 1" in stripped
        assert "Done." in stripped
        assert _ends_with_reset(result)

    def test_multiple_code_blocks(self):
        md = "First:\n```python\na = 1\n```\nSecond:\n```js\nb = 2\n```"
        result = _format_markdown(md)
        stripped = _strip_ansi(result)
        assert "a = 1" in stripped
        assert "b = 2" in stripped
        assert _ends_with_reset(result)

    def test_unclosed_code_block_during_streaming(self):
        md = "Here is code:\n```python\nx = 1\ny = 2"
        result = _format_markdown(md)
        stripped = _strip_ansi(result)
        assert "Here is code:" in stripped
        assert "x = 1" in stripped
        assert _ends_with_reset(result)

    def test_code_block_lang_with_special_chars(self):
        md = "```c++\nint x = 1;\n```"
        result = _format_markdown(md)
        assert "int x = 1;" in _strip_ansi(result)

    def test_empty_input(self):
        assert _format_markdown("") == ""

    def test_only_whitespace(self):
        assert _format_markdown("   \n\n  ") == ""

    def test_complete_then_unclosed_code_block(self):
        md = "```python\na = 1\n```\nNow:\n```js\nb = 2"
        result = _format_markdown(md)
        stripped = _strip_ansi(result)
        assert "a = 1" in stripped
        assert "b = 2" in stripped
        assert _ends_with_reset(result)


# -- Bug regression: styling leak after markdown --------------------------------

_SAVE_CURSOR = "\033[s"
_RESTORE_CURSOR = "\033[u"


class TestFormatCodeEndsWithReset:
    """_format_code must end with a full ANSI reset so styles don't bleed into
    subsequent plain text or the prompt."""

    def test_python_code_ends_with_reset(self):
        result = _format_code("x = 1\n", "python")
        assert _ends_with_reset(result)

    def test_unknown_lang_ends_with_reset(self):
        result = _format_code("hello\n", "nonexistent_lang_xyz")
        assert _ends_with_reset(result)

    def test_empty_lang_ends_with_reset(self):
        result = _format_code("x = 1\n", "")
        assert _ends_with_reset(result)


class TestFormatMarkdownNoStyleLeak:
    """After _format_markdown, no ANSI state should leak into subsequent output."""

    def test_code_block_followed_by_plain(self):
        md = "```python\nx = 1\n```\nAfter code."
        result = _format_markdown(md)
        assert _ends_with_reset(result)

    def test_bold_then_code_block(self):
        md = "**bold**\n```python\nx = 1\n```"
        result = _format_markdown(md)
        assert _ends_with_reset(result)

    def test_inline_code_then_code_block(self):
        md = "Use `foo` here:\n```python\nfoo()\n```"
        result = _format_markdown(md)
        assert _ends_with_reset(result)

    def test_multiple_code_blocks_each_reset(self):
        """Each code block should end with a full reset so that bold/color from
        Pygments doesn't leak into subsequent plain sections."""
        code1 = _format_code("a = 1\n", "python")
        code2 = _format_code("b = 2\n", "js")
        assert _ends_with_reset(code1), "First code block must end with reset"
        assert _ends_with_reset(code2), "Second code block must end with reset"
        md = "```python\na = 1\n```\nMiddle text\n```js\nb = 2\n```"
        result = _format_markdown(md)
        assert _ends_with_reset(result)


# -- Bug regression: scroll duplication ----------------------------------------


def _run_stream(fake_stream_fn):
    """Run _stream_response with a fake agent, returning all stdout writes."""
    agent = MagicMock()
    agent.stream = fake_stream_fn
    captured: list[str] = []

    with patch.object(sys, "stdout", new_callable=lambda: MagicMock):
        sys.stdout.write = lambda s: captured.append(s)
        sys.stdout.flush = lambda: None
        asyncio.run(_stream_response(agent, "test"))

    return captured


def _visible_text(writes):
    """Simulate what a terminal would display given a sequence of writes,
    handling cursor-up (\\033[NA) and erase-below (\\033[J) so we can
    verify the final visible result and detect duplication."""
    # Build a list of screen lines
    lines = [""]
    cursor_row = 0
    raw = "".join(writes)
    i = 0
    while i < len(raw):
        if raw[i] == "\033" and i + 1 < len(raw) and raw[i + 1] == "[":
            # Parse ANSI escape: \033[ <params> <letter>
            j = i + 2
            while j < len(raw) and raw[j] in "0123456789;":
                j += 1
            if j < len(raw):
                code = raw[j]
                params = raw[i + 2:j]
                if code == "A":  # cursor up
                    n = int(params) if params else 1
                    cursor_row = max(0, cursor_row - n)
                elif code == "J":  # erase below
                    del lines[cursor_row + 1:]
                    lines[cursor_row] = ""
                # Skip other escapes (colors etc) — they don't affect text content
                i = j + 1
                continue
        elif raw[i] == "\r":
            # Carriage return — move to start of current line
            lines[cursor_row] = ""
            i += 1
            continue
        elif raw[i] == "\n":
            cursor_row += 1
            if cursor_row >= len(lines):
                lines.append("")
            i += 1
            continue
        else:
            # Regular character — append to current line
            while cursor_row >= len(lines):
                lines.append("")
            lines[cursor_row] += raw[i]
            i += 1
            continue
        i += 1
    return lines


class TestStreamResponseNoDuplication:
    """After streaming, the visible terminal content should contain the
    response text exactly once — no duplicated lines from rewrites."""

    def test_no_save_restore_cursor(self):
        """Must not use save/restore cursor — they break when output scrolls."""

        async def fake_stream(text, handler):
            handler("Hello")
            handler("Hello world")

        writes = _run_stream(fake_stream)
        output = "".join(writes)
        assert _SAVE_CURSOR not in output
        assert _RESTORE_CURSOR not in output

    def test_single_line_no_duplication(self):
        """A single-line response updated multiple times should appear once."""

        async def fake_stream(text, handler):
            handler("Hello")
            handler("Hello world")
            handler("Hello world!")

        lines = _visible_text(_run_stream(fake_stream))
        visible = [l for l in lines if l.strip()]
        assert sum(1 for l in visible if "Hello" in l) == 1

    def test_multiline_no_duplication(self):
        """A multi-line response should not have any line duplicated."""

        async def fake_stream(text, handler):
            handler("Line 1")
            handler("Line 1\nLine 2")
            handler("Line 1\nLine 2\nLine 3")

        lines = _visible_text(_run_stream(fake_stream))
        visible = [l for l in lines if l.strip()]
        assert sum(1 for l in visible if "Line 1" in l) == 1
        assert sum(1 for l in visible if "Line 2" in l) == 1
        assert sum(1 for l in visible if "Line 3" in l) == 1

    def test_code_block_no_duplication(self):
        """Code blocks (which change formatting mid-stream) should not
        cause visible duplication."""

        async def fake_stream(text, handler):
            handler("Here:\n```python\nx = 1")
            handler("Here:\n```python\nx = 1\n```")
            handler("Here:\n```python\nx = 1\n```\nDone.")

        lines = _visible_text(_run_stream(fake_stream))
        visible = [l for l in lines if l.strip()]
        assert sum(1 for l in visible if "x = 1" in l) == 1
        assert sum(1 for l in visible if "Done." in l) == 1


# -- Bug regression: styling leak (prompt corruption) --------------------------


class TestStreamResponseStyling:
    """Streaming output must use _format_markdown (so formatting works)
    and must end with a full ANSI reset (so the prompt isn't corrupted)."""

    def test_output_contains_formatting(self):
        """The stream handler must use _format_markdown, producing ANSI
        escape codes for bold, inline code, and syntax highlighting."""

        async def fake_stream(text, handler):
            handler("**bold** and `code`")

        writes = _run_stream(fake_stream)
        output = "".join(writes)
        # Must contain ANSI escapes from formatting (bold \033[1m, cyan \033[36m)
        assert "\033[1m" in output, "Bold formatting missing"
        assert "\033[36m" in output, "Inline code formatting missing"

    def test_code_block_is_highlighted(self):
        """Code blocks must be syntax-highlighted via Pygments."""

        async def fake_stream(text, handler):
            handler("```python\nx = 1\n```")

        writes = _run_stream(fake_stream)
        output = "".join(writes)
        # Pygments TrueColor formatter produces \033[38;2;... sequences
        assert "\033[38;2;" in output, "Syntax highlighting missing"

    def test_final_output_ends_with_reset(self):
        """The very last thing written must be \\033[0m (+ newline) so no
        ANSI state leaks into prompt-toolkit's next prompt render."""

        async def fake_stream(text, handler):
            handler("```python\nx = 1\n```")

        writes = _run_stream(fake_stream)
        output = "".join(writes)
        assert output.endswith("\033[0m\n"), (
            f"Output must end with reset+newline, got: ...{output[-20:]!r}"
        )

    def test_format_code_ends_with_full_reset(self):
        """Each _format_code call must end with \\033[0m so Pygments colors
        don't bleed into subsequent plain text sections."""
        result = _format_code("x = 1\n", "python")
        assert result.endswith("\033[0m"), (
            "Pygments output must end with full reset"
        )
