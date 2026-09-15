"""The shipped skills must satisfy the Agent Skills specification.

Constraints come from https://agentskills.io/specification. Getting these wrong
means a host silently ignores the skill, which is hard to notice by hand.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / "skills"

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def skill_dirs() -> list[Path]:
    return sorted(p for p in SKILLS.iterdir() if (p / "SKILL.md").is_file())


def parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal YAML frontmatter reader: flat keys are all the spec requires."""
    if not text.startswith("---"):
        raise AssertionError("SKILL.md must begin with YAML frontmatter")
    _, block, _ = text.split("---", 2)
    data: dict[str, str] = {}
    key = None
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.startswith(("  ", "\t")) and key:
            continue  # nested mapping, e.g. metadata
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            data[key] = value.strip().strip("'\"")
    return data


def test_at_least_one_skill_ships():
    assert skill_dirs()


@pytest.mark.parametrize("skill", skill_dirs(), ids=lambda p: p.name)
class TestSkill:
    def test_name_matches_directory(self, skill):
        meta = parse_frontmatter((skill / "SKILL.md").read_text(encoding="utf-8"))
        assert meta.get("name") == skill.name

    def test_name_is_valid(self, skill):
        name = parse_frontmatter((skill / "SKILL.md").read_text(encoding="utf-8"))["name"]
        assert len(name) <= 64
        assert NAME_PATTERN.match(name), f"{name!r} must be lowercase, hyphen separated"

    def test_description_is_present_and_within_limit(self, skill):
        meta = parse_frontmatter((skill / "SKILL.md").read_text(encoding="utf-8"))
        description = meta.get("description", "")
        assert description, "description is required"
        assert len(description) <= 1024

    def test_description_says_when_to_use_it(self, skill):
        # The description is the only thing a host sees before activation, so it
        # has to carry the trigger conditions.
        description = parse_frontmatter((skill / "SKILL.md").read_text(encoding="utf-8"))[
            "description"
        ].lower()
        assert "use when" in description or "use this" in description

    def test_compatibility_within_limit(self, skill):
        meta = parse_frontmatter((skill / "SKILL.md").read_text(encoding="utf-8"))
        assert len(meta.get("compatibility", "")) <= 500

    def test_body_stays_short_enough_to_load(self, skill):
        # The spec recommends keeping SKILL.md under 500 lines; detail belongs
        # in references/ so it loads only when needed.
        lines = (skill / "SKILL.md").read_text(encoding="utf-8").splitlines()
        assert len(lines) < 500, f"{len(lines)} lines; move detail into references/"

    def test_referenced_files_exist(self, skill):
        body = (skill / "SKILL.md").read_text(encoding="utf-8")
        for target in re.findall(r"\]\((references/[^)]+)\)", body):
            assert (skill / target).is_file(), f"{target} is referenced but missing"


class TestPluginManifests:
    @pytest.mark.parametrize(
        "path",
        [
            "plugin.json",
            ".codex-plugin/plugin.json",
            ".claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json",
        ],
    )
    def test_is_valid_json(self, path):
        json.loads((REPO / path).read_text(encoding="utf-8"))

    def test_versions_agree(self):
        portable = json.loads((REPO / "plugin.json").read_text(encoding="utf-8"))
        codex = json.loads((REPO / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        claude = json.loads((REPO / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        assert portable["version"] == codex["version"] == claude["version"]

    def test_version_matches_the_package(self):
        from social_video import __version__

        portable = json.loads((REPO / "plugin.json").read_text(encoding="utf-8"))
        assert portable["version"] == __version__

    def test_codex_manifest_points_at_the_canonical_skills(self):
        codex = json.loads((REPO / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        assert codex["skills"] == "./skills/"
        assert (REPO / "skills").is_dir()
