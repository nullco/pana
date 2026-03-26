"""Tests for the bash tool."""

from __future__ import annotations

import asyncio

from pana.agents.tools import tool_bash


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
