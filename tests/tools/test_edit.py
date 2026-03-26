"""Tests for the edit tool."""

from __future__ import annotations

from pana.agents.tools import tool_edit


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
