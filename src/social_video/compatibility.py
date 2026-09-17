"""Fail closed when the installed CLI, plugin and canonical skill are mixed versions."""

from __future__ import annotations

import json
import re
from pathlib import Path

from social_video import __version__
from social_video.errors import ValidationError
from social_video.schemas.base import SCHEMA_VERSION

_SKILL_VERSION = re.compile(r"^\s*version:\s*[\"']?([^\s\"']+)", re.MULTILINE)


def component_versions(
    repository_root: Path | None = None, *, cli_version: str | None = None
) -> dict[str, str]:
    root = (repository_root or Path(__file__).resolve().parents[2]).resolve()
    versions = {"cli": cli_version or __version__, "schema": str(SCHEMA_VERSION)}
    plugin = root / ".codex-plugin" / "plugin.json"
    skill = root / "skills" / "social-video-agent" / "SKILL.md"
    package = root / "package.json"
    if plugin.is_file():
        versions["plugin"] = str(json.loads(plugin.read_text(encoding="utf-8"))["version"])
    if package.is_file():
        package_data = json.loads(package.read_text(encoding="utf-8"))
        versions["remotion_package"] = str(package_data["version"])
    if skill.is_file():
        match = _SKILL_VERSION.search(skill.read_text(encoding="utf-8"))
        if not match:
            raise ValidationError(f"canonical skill has no version field: {skill}")
        versions["skill"] = match.group(1)
    return versions


def validate_component_versions(
    repository_root: Path | None = None, *, cli_version: str | None = None
) -> dict[str, str]:
    versions = component_versions(repository_root, cli_version=cli_version)
    release_versions = {value for key, value in versions.items() if key != "schema"}
    if len(release_versions) > 1:
        detail = ", ".join(f"{key}={value}" for key, value in sorted(versions.items()))
        raise ValidationError(
            "social-video-agent components come from different releases "
            f"({detail}). Re-run `./scripts/wsl/bootstrap.sh`, reopen Codex, then run "
            "`social-video-agent version` before resuming the workflow."
        )
    return versions


def validate_saved_versions(saved: dict[str, str]) -> None:
    current = validate_component_versions()
    for key in ("cli", "skill", "plugin", "schema"):
        if key in saved and key in current and saved[key] != current[key]:
            raise ValidationError(
                f"workflow was created with {key}={saved[key]}, but the active component is "
                f"{current[key]}. Run bootstrap/update and migrate or recreate this workspace."
            )
