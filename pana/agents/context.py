"""Discover and collect AGENTS.md files for injection into agent system prompt."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT_MARKERS = {".git", "pyproject.toml", "setup.py", "setup.cfg", "package.json"}
AGENTS_FILENAME = "AGENTS.md"


def find_project_root(start: Path | None = None) -> Path:
    """Walk upward from start (default: cwd) to find the project root."""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        if any((directory / marker).exists() for marker in PROJECT_ROOT_MARKERS):
            return directory
    return current


def collect_agents_md(root: Path | None = None) -> str:
    """Discover all AGENTS.md files under the project root and return concatenated content.

    Each file's content is prefixed with a header showing its relative path.
    """
    project_root = find_project_root(root)
    agents_files = sorted(project_root.rglob(AGENTS_FILENAME))

    # Skip anything inside hidden dirs or .venv/node_modules
    skip_parts = {".venv", "node_modules", "__pycache__"}
    agents_files = [
        f for f in agents_files if not (skip_parts & set(f.relative_to(project_root).parts))
    ]

    if not agents_files:
        logger.debug("No AGENTS.md files found under %s", project_root)
        return ""

    sections = []
    for filepath in agents_files:
        rel_path = filepath.relative_to(project_root)
        try:
            content = filepath.read_text(encoding="utf-8").strip()
        except OSError:
            logger.warning("Failed to read %s", filepath)
            continue
        if content:
            sections.append(f"## {rel_path}\n\n{content}")
            logger.debug("Loaded AGENTS.md: %s", rel_path)

    if not sections:
        return ""

    return "# Project Context\n\nProject-specific instructions and guidelines:\n\n" + "\n\n".join(
        sections
    )
