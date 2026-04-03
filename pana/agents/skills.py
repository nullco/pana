"""Discover, parse, and activate Agent Skills (agentskills.io)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)
_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".ruff_cache", ".pytest_cache"}
MAX_SCAN_DEPTH = 4


@dataclass
class Skill:
    """A parsed Agent Skill."""

    name: str
    description: str
    location: Path
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    body: str | None = None

    @property
    def base_dir(self) -> Path:
        return self.location.parent


def _parse_yaml_frontmatter(raw: str) -> dict[str, str | dict[str, str] | None]:
    """Minimal YAML frontmatter parser (avoids adding a PyYAML dependency).

    Handles the subset of YAML used by SKILL.md frontmatter:
    scalar key-value pairs and one level of nested mapping (``metadata``).
    """
    result: dict[str, str | dict[str, str] | None] = {}
    current_map_key: str | None = None
    current_map: dict[str, str] = {}

    for line in raw.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue

        # Nested mapping value (indented "  key: value")
        if line.startswith(("  ", "\t")) and current_map_key is not None:
            stripped = line.strip()
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                current_map[k.strip()] = v.strip().strip('"').strip("'")
            continue

        # Flush any accumulated nested map
        if current_map_key is not None:
            result[current_map_key] = dict(current_map)
            current_map_key = None
            current_map = {}

        if ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if not value:
            # Could be start of a nested mapping
            current_map_key = key
        else:
            result[key] = value.strip('"').strip("'")

    # Flush trailing nested map
    if current_map_key is not None:
        result[current_map_key] = dict(current_map)

    return result


def parse_skill_md(path: Path) -> Skill | None:
    """Parse a SKILL.md file into a Skill, or return None on failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Cannot read %s", path)
        return None

    match = _FRONTMATTER_RE.match(text)
    if not match:
        logger.warning("No YAML frontmatter in %s", path)
        return None

    raw_yaml, body = match.group(1), match.group(2).strip()

    try:
        fm = _parse_yaml_frontmatter(raw_yaml)
    except Exception:
        logger.warning("Unparseable YAML in %s", path)
        return None

    name = fm.get("name")
    description = fm.get("description")

    if not name or not isinstance(name, str):
        logger.warning("Missing 'name' in %s", path)
        return None
    if not description or not isinstance(description, str):
        logger.warning("Missing 'description' in %s — skipping", path)
        return None

    # Lenient validation: warn but still load
    if not _NAME_RE.match(name):
        logger.warning("Skill name %r in %s doesn't match naming convention", name, path)
    if name != path.parent.name:
        logger.warning(
            "Skill name %r doesn't match directory %r in %s", name, path.parent.name, path
        )

    allowed_tools_raw = fm.get("allowed-tools")
    allowed_tools = (
        allowed_tools_raw.split() if isinstance(allowed_tools_raw, str) else []
    )
    raw_metadata = fm.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}

    return Skill(
        name=name,
        description=description,
        location=path.resolve(),
        license=fm.get("license") if isinstance(fm.get("license"), str) else None,
        compatibility=fm.get("compatibility") if isinstance(fm.get("compatibility"), str) else None,
        metadata=metadata,
        allowed_tools=allowed_tools,
        body=body or None,
    )


def _scan_skills_dir(base: Path, depth: int = 0) -> list[Path]:
    """Find SKILL.md files under *base*, limited to MAX_SCAN_DEPTH."""
    results: list[Path] = []
    if depth > MAX_SCAN_DEPTH or not base.is_dir():
        return results
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return results
    for entry in entries:
        if not entry.is_dir() or entry.name in SKIP_DIRS:
            continue
        skill_file = entry / "SKILL.md"
        if skill_file.is_file():
            results.append(skill_file)
        else:
            results.extend(_scan_skills_dir(entry, depth + 1))
    return results


def discover_skills(
    project_root: Path | None = None,
    home: Path | None = None,
) -> list[Skill]:
    """Discover all Agent Skills from conventional directories.

    Scan order (first match wins on name collision):
    1. <project>/.pana/skills/
    2. <project>/.agents/skills/
    3. ~/.pana/skills/
    4. ~/.agents/skills/
    """
    from pana.agents.context import find_project_root

    root = project_root or find_project_root()
    home_dir = home or Path.home()

    search_dirs = [
        root / ".pana" / "skills",
        root / ".agents" / "skills",
        home_dir / ".pana" / "skills",
        home_dir / ".agents" / "skills",
    ]

    seen_names: dict[str, Skill] = {}
    for search_dir in search_dirs:
        for skill_path in _scan_skills_dir(search_dir):
            skill = parse_skill_md(skill_path)
            if skill is None:
                continue
            if skill.name in seen_names:
                logger.debug(
                    "Skill %r from %s shadowed by earlier %s",
                    skill.name,
                    skill.location,
                    seen_names[skill.name].location,
                )
                continue
            seen_names[skill.name] = skill

    return list(seen_names.values())


def build_skills_catalog(skills: list[Skill]) -> str:
    """Build the system-prompt catalog section for discovered skills."""
    if not skills:
        return ""

    entries = []
    for s in skills:
        entries.append(
            f"  <skill>\n"
            f"    <name>{s.name}</name>\n"
            f"    <description>{s.description}</description>\n"
            f"    <location>{s.location}</location>\n"
            f"  </skill>"
        )

    catalog = "<available_skills>\n" + "\n".join(entries) + "\n</available_skills>"

    instructions = (
        "The following skills provide specialized instructions for specific tasks.\n"
        "When a task matches a skill's description, use the read tool to load\n"
        "the SKILL.md at the listed location before proceeding.\n"
        "When a skill references relative paths, resolve them against the skill's\n"
        "directory (the parent of SKILL.md) and use absolute paths in tool calls.\n"
        "You usually only need to load a skill once per conversation.\n\n"
    )

    return instructions + catalog


def list_skill_resources(skill: Skill) -> list[str]:
    """Return relative paths of bundled files in a skill directory."""
    resources: list[str] = []
    base = skill.base_dir
    if not base.is_dir():
        return resources
    for child in sorted(base.rglob("*")):
        if child.is_file() and child.name != "SKILL.md":
            resources.append(str(child.relative_to(base)))
    return resources
