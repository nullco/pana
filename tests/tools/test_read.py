"""Tests for the read tool."""

from __future__ import annotations

from pana.agents.tools import tool_read


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
