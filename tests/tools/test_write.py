"""Tests for the write tool."""

from __future__ import annotations

from pana.agents.tools import tool_write


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
