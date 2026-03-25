"""Tests for AGENTS.md discovery and collection."""

from pathlib import Path

from pana.agents.context import collect_agents_md, find_project_root


def test_find_project_root_with_git(tmp_path):
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert find_project_root(sub) == tmp_path


def test_find_project_root_with_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").touch()
    assert find_project_root(tmp_path) == tmp_path


def test_find_project_root_fallback(tmp_path):
    sub = tmp_path / "no_markers"
    sub.mkdir()
    assert find_project_root(sub) == sub


def test_collect_agents_md_none(tmp_path):
    (tmp_path / ".git").mkdir()
    assert collect_agents_md(tmp_path) == ""


def test_collect_agents_md_root_only(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("# Root instructions\nDo things.")
    result = collect_agents_md(tmp_path)
    assert "# Project Context" in result
    assert "## AGENTS.md" in result
    assert "Do things." in result


def test_collect_agents_md_hierarchical(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("Root context")
    sub = tmp_path / "src" / "api"
    sub.mkdir(parents=True)
    (sub / "AGENTS.md").write_text("API context")
    result = collect_agents_md(tmp_path)
    assert "## AGENTS.md" in result
    assert "## src/api/AGENTS.md" in result
    assert "Root context" in result
    assert "API context" in result


def test_collect_agents_md_skips_venv(tmp_path):
    (tmp_path / ".git").mkdir()
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "AGENTS.md").write_text("Should be skipped")
    (tmp_path / "AGENTS.md").write_text("Keep this")
    result = collect_agents_md(tmp_path)
    assert "Should be skipped" not in result
    assert "Keep this" in result


def test_collect_agents_md_skips_node_modules(tmp_path):
    (tmp_path / ".git").mkdir()
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "AGENTS.md").write_text("npm stuff")
    assert collect_agents_md(tmp_path) == ""


def test_collect_agents_md_empty_file(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("")
    assert collect_agents_md(tmp_path) == ""
