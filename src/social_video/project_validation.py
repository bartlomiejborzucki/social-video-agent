"""Offline validation for the repository's Codex plugin distribution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
SKILL_LINK = re.compile(r"\[[^]]+\]\(([^)#]+)(?:#[^)]+)?\)")


@dataclass(frozen=True)
class ValidationResult:
    name: str
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def _load_json(path: Path) -> tuple[dict[str, object] | None, list[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{path}: {exc}"]
    if not isinstance(value, dict):
        return None, [f"{path}: root must be an object"]
    return value, []


def validate_plugin(path: Path) -> ValidationResult:
    manifest = path / ".codex-plugin" / "plugin.json" if path.is_dir() else path
    data, errors = _load_json(manifest)
    if data is None:
        return ValidationResult("plugin manifest", tuple(errors))

    required_strings = ("name", "version", "description", "homepage", "repository", "license")
    for field in required_strings:
        if not isinstance(data.get(field), str) or not str(data[field]).strip():
            errors.append(f"{manifest}: {field} must be a non-empty string")
    if isinstance(data.get("version"), str) and not SEMVER.fullmatch(str(data["version"])):
        errors.append(f"{manifest}: version must be strict SemVer")
    author = data.get("author")
    if not isinstance(author, dict) or not isinstance(author.get("name"), str):
        errors.append(f"{manifest}: author.name is required")
    interface = data.get("interface")
    interface_fields = (
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
        "capabilities",
        "defaultPrompt",
    )
    if not isinstance(interface, dict):
        errors.append(f"{manifest}: interface must be an object")
    else:
        for field in interface_fields:
            if field not in interface:
                errors.append(f"{manifest}: interface.{field} is required")
        prompts = interface.get("defaultPrompt")
        if not isinstance(prompts, list) or not 1 <= len(prompts) <= 3:
            errors.append(f"{manifest}: interface.defaultPrompt must contain 1-3 prompts")
    skills = data.get("skills")
    if not isinstance(skills, str) or not skills.startswith("./"):
        errors.append(f"{manifest}: skills must be a relative ./ path")
    elif not (manifest.parent.parent / skills).resolve().is_dir():
        errors.append(f"{manifest}: skills path does not exist: {skills}")
    if "hooks" in data:
        errors.append(f"{manifest}: hooks is not supported by the current validator")
    return ValidationResult("plugin manifest", tuple(errors))


def validate_marketplace(path: Path) -> ValidationResult:
    data, errors = _load_json(path)
    if data is None:
        return ValidationResult("marketplace", tuple(errors))
    if not isinstance(data.get("name"), str) or not data["name"]:
        errors.append(f"{path}: name is required")
    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        errors.append(f"{path}: plugins must be a non-empty array")
        return ValidationResult("marketplace", tuple(errors))
    for index, entry in enumerate(plugins):
        label = f"{path}: plugins[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue
        source = entry.get("source")
        policy = entry.get("policy")
        if not isinstance(source, dict) or source.get("source") != "local":
            errors.append(f"{label}.source must declare source=local")
        else:
            relative = source.get("path")
            if not isinstance(relative, str) or not relative.startswith("./plugins/"):
                errors.append(f"{label}.source.path must start with ./plugins/")
            elif not (path.parents[2] / relative).resolve().is_dir():
                errors.append(f"{label}.source.path does not exist: {relative}")
        if not isinstance(policy, dict):
            errors.append(f"{label}.policy is required")
        else:
            if policy.get("installation") not in {
                "NOT_AVAILABLE",
                "AVAILABLE",
                "INSTALLED_BY_DEFAULT",
            }:
                errors.append(f"{label}.policy.installation is invalid")
            if policy.get("authentication") not in {"ON_INSTALL", "ON_USE"}:
                errors.append(f"{label}.policy.authentication is invalid")
        if not isinstance(entry.get("category"), str):
            errors.append(f"{label}.category is required")
    return ValidationResult("marketplace", tuple(errors))


def validate_skill(path: Path) -> ValidationResult:
    skill_file = path / "SKILL.md" if path.is_dir() else path
    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError as exc:
        return ValidationResult("skill", (f"{skill_file}: {exc}",))
    errors: list[str] = []
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        errors.append(f"{skill_file}: missing YAML frontmatter")
        return ValidationResult("skill", tuple(errors))
    frontmatter = text.split("\n---\n", 1)[0]
    expected_name = skill_file.parent.name
    if f"name: {expected_name}" not in frontmatter:
        errors.append(f"{skill_file}: name must match directory {expected_name!r}")
    if "description:" not in frontmatter:
        errors.append(f"{skill_file}: description is required")
    if "[TODO:" in text:
        errors.append(f"{skill_file}: unfinished TODO placeholder")
    for relative in SKILL_LINK.findall(text):
        if "://" not in relative and not (skill_file.parent / relative).is_file():
            errors.append(f"{skill_file}: broken relative link {relative}")
    return ValidationResult("skill", tuple(errors))
