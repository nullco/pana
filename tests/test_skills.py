"""Tests for Agent Skills discovery, parsing, and catalog generation."""

from pathlib import Path

from pana.agents.skills import (
    Skill,
    build_skills_catalog,
    discover_skills,
    list_skill_resources,
    parse_skill_md,
)


def _make_skill_dir(base: Path, name: str, content: str) -> Path:
    """Helper: create a skill directory with a SKILL.md file."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content)
    return skill_dir


VALID_SKILL_MD = """\
---
name: pdf-processing
description: Extract PDF text, fill forms, merge files. Use when handling PDFs.
license: Apache-2.0
metadata:
  author: example-org
  version: "1.0"
---

# PDF Processing

Use pdfplumber for text extraction.
"""

MINIMAL_SKILL_MD = """\
---
name: code-review
description: Review code for quality and style issues.
---
"""


class TestParseSkillMd:
    def test_valid_full(self, tmp_path: Path) -> None:
        _make_skill_dir(tmp_path, "pdf-processing", VALID_SKILL_MD)
        skill = parse_skill_md(tmp_path / "pdf-processing" / "SKILL.md")
        assert skill is not None
        assert skill.name == "pdf-processing"
        assert skill.description.startswith("Extract PDF text")
        assert skill.license == "Apache-2.0"
        assert skill.metadata == {"author": "example-org", "version": "1.0"}
        assert skill.body is not None
        assert "pdfplumber" in skill.body

    def test_minimal(self, tmp_path: Path) -> None:
        _make_skill_dir(tmp_path, "code-review", MINIMAL_SKILL_MD)
        skill = parse_skill_md(tmp_path / "code-review" / "SKILL.md")
        assert skill is not None
        assert skill.name == "code-review"
        assert skill.description == "Review code for quality and style issues."
        assert skill.license is None
        assert skill.body is None

    def test_missing_description_skips(self, tmp_path: Path) -> None:
        content = "---\nname: broken\n---\nSome body.\n"
        _make_skill_dir(tmp_path, "broken", content)
        skill = parse_skill_md(tmp_path / "broken" / "SKILL.md")
        assert skill is None

    def test_missing_name_skips(self, tmp_path: Path) -> None:
        content = "---\ndescription: Some desc.\n---\nBody.\n"
        _make_skill_dir(tmp_path, "no-name", content)
        skill = parse_skill_md(tmp_path / "no-name" / "SKILL.md")
        assert skill is None

    def test_no_frontmatter_skips(self, tmp_path: Path) -> None:
        _make_skill_dir(tmp_path, "bad", "# No frontmatter here\n")
        skill = parse_skill_md(tmp_path / "bad" / "SKILL.md")
        assert skill is None

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        skill = parse_skill_md(tmp_path / "ghost" / "SKILL.md")
        assert skill is None

    def test_allowed_tools(self, tmp_path: Path) -> None:
        content = "---\nname: tooled\ndescription: Has tools.\nallowed-tools: Bash Read\n---\n"
        _make_skill_dir(tmp_path, "tooled", content)
        skill = parse_skill_md(tmp_path / "tooled" / "SKILL.md")
        assert skill is not None
        assert skill.allowed_tools == ["Bash", "Read"]

    def test_name_mismatch_warns_but_loads(self, tmp_path: Path) -> None:
        content = "---\nname: different-name\ndescription: Mismatched.\n---\n"
        _make_skill_dir(tmp_path, "actual-dir", content)
        skill = parse_skill_md(tmp_path / "actual-dir" / "SKILL.md")
        assert skill is not None
        assert skill.name == "different-name"

    def test_compatibility_field(self, tmp_path: Path) -> None:
        content = (
            "---\nname: needs-docker\ndescription: Needs docker.\n"
            "compatibility: Requires docker and jq\n---\n"
        )
        _make_skill_dir(tmp_path, "needs-docker", content)
        skill = parse_skill_md(tmp_path / "needs-docker" / "SKILL.md")
        assert skill is not None
        assert skill.compatibility == "Requires docker and jq"


class TestDiscoverSkills:
    def test_discovers_from_project_agents(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / ".agents" / "skills"
        _make_skill_dir(skills_dir, "my-skill", MINIMAL_SKILL_MD.replace("code-review", "my-skill"))
        skills = discover_skills(project_root=tmp_path, home=tmp_path / "fakehome")
        assert len(skills) == 1
        assert skills[0].name == "my-skill"

    def test_discovers_from_project_pana(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / ".pana" / "skills"
        _make_skill_dir(
            skills_dir, "pana-skill",
            MINIMAL_SKILL_MD.replace("code-review", "pana-skill"),
        )
        skills = discover_skills(project_root=tmp_path, home=tmp_path / "fakehome")
        assert len(skills) == 1
        assert skills[0].name == "pana-skill"

    def test_discovers_from_user_agents(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        skills_dir = home / ".agents" / "skills"
        _make_skill_dir(
            skills_dir, "user-skill",
            MINIMAL_SKILL_MD.replace("code-review", "user-skill"),
        )
        skills = discover_skills(project_root=tmp_path / "project", home=home)
        assert len(skills) == 1
        assert skills[0].name == "user-skill"

    def test_project_overrides_user(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        project = tmp_path / "project"
        # User-level skill
        _make_skill_dir(
            home / ".agents" / "skills", "shared",
            "---\nname: shared\ndescription: User version.\n---\n",
        )
        # Project-level skill with same name
        _make_skill_dir(
            project / ".agents" / "skills", "shared",
            "---\nname: shared\ndescription: Project version.\n---\n",
        )
        skills = discover_skills(project_root=project, home=home)
        assert len(skills) == 1
        assert skills[0].description == "Project version."

    def test_pana_dir_has_priority_over_agents_dir(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        _make_skill_dir(
            project / ".pana" / "skills", "dup",
            "---\nname: dup\ndescription: From pana.\n---\n",
        )
        _make_skill_dir(
            project / ".agents" / "skills", "dup",
            "---\nname: dup\ndescription: From agents.\n---\n",
        )
        skills = discover_skills(project_root=project, home=tmp_path / "fakehome")
        assert len(skills) == 1
        assert skills[0].description == "From pana."

    def test_no_skills(self, tmp_path: Path) -> None:
        skills = discover_skills(project_root=tmp_path, home=tmp_path / "fakehome")
        assert skills == []

    def test_skips_invalid_skills(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / ".agents" / "skills"
        _make_skill_dir(skills_dir, "good", MINIMAL_SKILL_MD.replace("code-review", "good"))
        _make_skill_dir(skills_dir, "bad", "---\nname: bad\n---\n")  # no description
        skills = discover_skills(project_root=tmp_path, home=tmp_path / "fakehome")
        assert len(skills) == 1
        assert skills[0].name == "good"


class TestBuildSkillsCatalog:
    def test_empty_returns_empty(self) -> None:
        assert build_skills_catalog([]) == ""

    def test_contains_skill_info(self, tmp_path: Path) -> None:
        skill = Skill(
            name="test-skill",
            description="A test skill.",
            location=tmp_path / "test-skill" / "SKILL.md",
        )
        catalog = build_skills_catalog([skill])
        assert "<available_skills>" in catalog
        assert "<name>test-skill</name>" in catalog
        assert "<description>A test skill.</description>" in catalog
        assert "read tool" in catalog.lower() or "read" in catalog

    def test_multiple_skills(self, tmp_path: Path) -> None:
        skills = [
            Skill(name="a", description="Skill A.", location=tmp_path / "a" / "SKILL.md"),
            Skill(name="b", description="Skill B.", location=tmp_path / "b" / "SKILL.md"),
        ]
        catalog = build_skills_catalog(skills)
        assert "<name>a</name>" in catalog
        assert "<name>b</name>" in catalog


class TestListSkillResources:
    def test_lists_files(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(MINIMAL_SKILL_MD)
        scripts = skill_dir / "scripts"
        scripts.mkdir()
        (scripts / "run.py").write_text("print('hi')")
        (skill_dir / "references").mkdir()
        (skill_dir / "references" / "guide.md").write_text("# Guide")

        skill = Skill(
            name="my-skill",
            description="Test.",
            location=skill_dir / "SKILL.md",
        )
        resources = list_skill_resources(skill)
        assert "scripts/run.py" in resources
        assert "references/guide.md" in resources
        assert "SKILL.md" not in [r.split("/")[-1] for r in resources]

    def test_empty_skill(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "empty"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(MINIMAL_SKILL_MD)
        skill = Skill(name="empty", description="Test.", location=skill_dir / "SKILL.md")
        assert list_skill_resources(skill) == []
