"""Tests for agents/tools.py — read, bash, edit, write."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from pana.agents.tools import tool_bash, tool_edit, tool_read, tool_write


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir(tmp_path):
    """Change to a temp directory for the duration of the test."""
    old = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(old)


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


class TestRead:
    def test_read_file(self, tmp_dir):
        f = tmp_dir / "hello.txt"
        f.write_text("line1\nline2\nline3\n")
        result = tool_read("hello.txt")
        assert "line1" in result
        assert "line3" in result

    def test_read_absolute_path(self, tmp_dir):
        f = tmp_dir / "abs.txt"
        f.write_text("absolute content")
        result = tool_read(str(f))
        assert "absolute content" in result

    def test_read_missing_file(self, tmp_dir):
        result = tool_read("nonexistent.txt")
        assert "Error" in result
        assert "not found" in result

    def test_read_directory(self, tmp_dir):
        d = tmp_dir / "subdir"
        d.mkdir()
        result = tool_read("subdir")
        assert "Error" in result

    def test_read_with_offset(self, tmp_dir):
        f = tmp_dir / "lines.txt"
        f.write_text("a\nb\nc\nd\ne\n")
        result = tool_read("lines.txt", offset=3)
        assert result.startswith("c")
        assert "a" not in result

    def test_read_with_limit(self, tmp_dir):
        f = tmp_dir / "lines.txt"
        f.write_text("alpha\nbeta\ngamma\ndelta\nepsilon\n")
        result = tool_read("lines.txt", limit=2)
        assert "alpha" in result
        assert "beta" in result
        assert "gamma" not in result
        # Continuation hint should tell the model how to proceed
        assert "offset=3" in result

    def test_read_with_offset_and_limit(self, tmp_dir):
        f = tmp_dir / "lines.txt"
        f.write_text("a\nb\nc\nd\ne\n")
        result = tool_read("lines.txt", offset=2, limit=2)
        assert "b" in result
        assert "c" in result
        assert "a" not in result
        assert "d" not in result

    def test_read_image_file(self, tmp_dir):
        f = tmp_dir / "photo.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        result = tool_read("photo.png")
        assert "Image file" in result
        assert "photo.png" in result

    def test_read_truncation(self, tmp_dir):
        f = tmp_dir / "big.txt"
        # Write more than 2000 lines
        f.write_text("\n".join(f"line{i}" for i in range(3000)))
        result = tool_read("big.txt")
        # Pi-style: actionable continuation hint instead of generic "truncated"
        assert "offset=" in result
        assert "to continue" in result


# ---------------------------------------------------------------------------
# bash
# ---------------------------------------------------------------------------


class TestBash:
    def test_echo(self, tmp_dir):
        result = asyncio.run(tool_bash("echo hello"))
        assert "hello" in result

    def test_stderr(self, tmp_dir):
        result = asyncio.run(tool_bash("echo err >&2"))
        assert "err" in result

    def test_exit_code(self, tmp_dir):
        result = asyncio.run(tool_bash("exit 42"))
        assert "42" in result

    def test_timeout(self, tmp_dir):
        result = asyncio.run(tool_bash("sleep 10", timeout=1))
        assert "timed out" in result

    def test_cwd(self, tmp_dir):
        result = asyncio.run(tool_bash("pwd"))
        assert str(tmp_dir) in result

    def test_no_output(self, tmp_dir):
        result = asyncio.run(tool_bash("true"))
        assert result == "(no output)"

    def test_multiline_output(self, tmp_dir):
        result = asyncio.run(tool_bash("echo a && echo b && echo c"))
        assert "a" in result
        assert "b" in result
        assert "c" in result


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


class TestEdit:
    def test_edit_basic(self, tmp_dir):
        f = tmp_dir / "file.txt"
        f.write_text("hello world")
        result = tool_edit("file.txt", "hello", "goodbye")
        assert "Successfully" in result
        assert f.read_text() == "goodbye world"

    def test_edit_preserves_rest(self, tmp_dir):
        f = tmp_dir / "file.txt"
        f.write_text("aaa\nbbb\nccc\n")
        result = tool_edit("file.txt", "bbb", "BBB")
        assert "Successfully" in result
        assert f.read_text() == "aaa\nBBB\nccc\n"

    def test_edit_not_found(self, tmp_dir):
        f = tmp_dir / "file.txt"
        f.write_text("hello world")
        result = tool_edit("file.txt", "xyz", "abc")
        assert "Error" in result
        assert "not found" in result
        assert f.read_text() == "hello world"  # unchanged

    def test_edit_missing_file(self, tmp_dir):
        result = tool_edit("nonexistent.txt", "a", "b")
        assert "Error" in result

    def test_edit_multiple_occurrences(self, tmp_dir):
        f = tmp_dir / "file.txt"
        f.write_text("aaa bbb aaa ccc aaa")
        result = tool_edit("file.txt", "aaa", "XXX")
        assert "first of 3" in result
        assert f.read_text() == "XXX bbb aaa ccc aaa"

    def test_edit_whitespace_exact(self, tmp_dir):
        f = tmp_dir / "file.py"
        f.write_text("    def foo():\n        pass\n")
        result = tool_edit("file.py", "    def foo():\n        pass", "    def foo():\n        return 42")
        assert "Successfully" in result
        assert "return 42" in f.read_text()


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


class TestWrite:
    def test_write_new_file(self, tmp_dir):
        result = tool_write("new.txt", "content here")
        assert "Successfully" in result
        assert (tmp_dir / "new.txt").read_text() == "content here"

    def test_write_overwrite(self, tmp_dir):
        f = tmp_dir / "existing.txt"
        f.write_text("old content")
        result = tool_write("existing.txt", "new content")
        assert "Successfully" in result
        assert f.read_text() == "new content"

    def test_write_creates_parents(self, tmp_dir):
        result = tool_write("a/b/c/deep.txt", "deep content")
        assert "Successfully" in result
        assert (tmp_dir / "a" / "b" / "c" / "deep.txt").read_text() == "deep content"

    def test_write_reports_size(self, tmp_dir):
        content = "x" * 100
        result = tool_write("sized.txt", content)
        assert "100 bytes" in result

    def test_write_empty(self, tmp_dir):
        result = tool_write("empty.txt", "")
        assert "Successfully" in result
        assert (tmp_dir / "empty.txt").read_text() == ""
