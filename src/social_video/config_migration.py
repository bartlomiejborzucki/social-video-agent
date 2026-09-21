"""Explicit migration of pre-0.4 project configuration to the executable contract.

Before 0.4 a project config was discovery context: free prose was welcome,
because nothing rendered from it. From 0.4 the same file compiles into
``brand-contract.json`` and drives the renderer, so every value has to mean one
thing.

Two classes of change are handled differently on purpose:

* A rename or a YAML scalar type is carried over silently. ``logo`` and
  ``logo_file`` name the same file, and ``30`` and ``"30"`` are the same frame
  rate, so converting them cannot change how the edit looks.
* A value that encoded an editorial decision is never guessed. ``restrained``
  is not a number, ``subtle`` is neither an outline nor a shadow, and a margin
  of ``0.15`` is 15% of the frame under the old fraction reading but a
  hairline under the new percentage one. Each of those becomes a
  :class:`~social_video.errors.ConfigMigrationError` naming the field, the old
  value, and what has to be written instead.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from social_video.errors import ConfigMigrationError
from social_video.schemas.config import CaptionConfig, ProjectVideoConfig

MIGRATION_DOC = "docs/migrations/0.4-brand-contract.md"

#: Pure renames. The value keeps its meaning, so these are applied silently.
LEGACY_ALIASES: dict[str, str] = {
    "logo": "logo_file",
    "preferred_output_directory": "delivery_output",
}

#: Fields whose old descriptive wording has no single correct replacement.
#: The text is appended to the generated "allowed values" line.
FIELD_GUIDANCE: dict[str, str] = {
    "music_policy": (
        "the contract only records whether a bed is forbidden (none), allowed "
        "(optional) or expected (required); keep the descriptive rule in the "
        "brandbook or AGENTS.md, where it stays readable"
    ),
    "sfx_policy": (
        "the contract only records whether effects are forbidden (none), "
        "allowed (optional) or expected (required); keep the descriptive rule "
        "in the brandbook or AGENTS.md"
    ),
    "image_generation_policy": (
        "this is a consent decision: none refuses cloud image calls, optional "
        "allows them, required expects generated plates"
    ),
    "default_fps_policy": (
        "the contract must name one output rate; read the source rate with "
        "`social-video-agent inspect SOURCE` and choose deliberately rather "
        "than following the source"
    ),
    "caption_style.outline_or_shadow": (
        "the old wording described how strong the edge was, not which edge is "
        "drawn; pick the kind here and tune its strength in the brand profile"
    ),
    "logo_usage": (
        "required makes an edit without a logo fail, optional draws it when it "
        "fits, none never draws it"
    ),
}

#: Numeric 0..1 fields that used to accept words.
RATIO_GUIDANCE: dict[str, str] = {
    "punch_in_intensity": (
        "0 holds the frame, 1 is the strongest push; the shipped template uses "
        "0.25 for a restrained look"
    ),
    "broll_density": ("0 never cuts away, 1 cuts away constantly; the shipped template uses 0"),
}

#: Percentage-of-height fields. A value below 1 almost certainly predates the
#: switch from fractions to percentages, and silently means something else now.
PERCENT_FIELDS: tuple[str, ...] = ("caption_style.bottom_margin_pct",)


@dataclass(frozen=True)
class MigrationIssue:
    """One field that a human, not this code, has to decide."""

    field: str
    value: Any
    reason: str
    instruction: str

    def render(self) -> str:
        return (
            f"  {self.field}: {self.value!r}\n    why: {self.reason}\n    fix: {self.instruction}"
        )


def migrate_project_config(raw: Mapping[str, Any], *, source: str | None = None) -> dict[str, Any]:
    """Return the 0.4+ mapping, or raise with one instruction per stale field."""
    migrated, issues = plan_migration(raw)
    if issues:
        raise ConfigMigrationError(_format(issues, source))
    return migrated


def plan_migration(raw: Mapping[str, Any]) -> tuple[dict[str, Any], list[MigrationIssue]]:
    """Apply the lossless part of the migration and report what is left."""
    migrated: dict[str, Any] = {
        key: dict(value) if key == "caption_style" and isinstance(value, dict) else value
        for key, value in raw.items()
    }
    issues: list[MigrationIssue] = []
    _apply_aliases(migrated, issues)
    _check_schema_version(migrated, issues)
    _check_unknown_keys(migrated, issues)
    _check_choices(migrated, issues)
    _check_ratios(migrated, issues)
    _check_percentages(migrated, issues)
    _check_font_family(migrated, issues)
    issues.sort(key=lambda issue: issue.field)
    return migrated, issues


def _apply_aliases(migrated: dict[str, Any], issues: list[MigrationIssue]) -> None:
    for legacy, current in LEGACY_ALIASES.items():
        if legacy not in migrated:
            continue
        value = migrated.pop(legacy)
        if current in migrated and migrated[current] != value:
            issues.append(
                MigrationIssue(
                    field=legacy,
                    value=value,
                    reason=(
                        f"{legacy!r} was renamed to {current!r}, but both are set to "
                        f"different values ({migrated[current]!r})"
                    ),
                    instruction=(
                        f"delete {legacy!r}; only {current!r} is read, and dropping one "
                        "of two different values silently is exactly what this refuses "
                        "to do"
                    ),
                )
            )
            continue
        migrated[current] = value


def _check_schema_version(migrated: dict[str, Any], issues: list[MigrationIssue]) -> None:
    version = migrated.setdefault("schema_version", 1)
    if version != 1:
        issues.append(
            MigrationIssue(
                field="schema_version",
                value=version,
                reason="this release compiles schema_version 1 only",
                instruction="set `schema_version: 1`",
            )
        )


def _check_unknown_keys(migrated: dict[str, Any], issues: list[MigrationIssue]) -> None:
    _report_unknown(migrated, ProjectVideoConfig, "", issues)
    style = migrated.get("caption_style")
    if isinstance(style, dict):
        _report_unknown(style, CaptionConfig, "caption_style.", issues)


def _report_unknown(
    values: Mapping[str, Any],
    model: type[BaseModel],
    prefix: str,
    issues: list[MigrationIssue],
) -> None:
    known = set(model.model_fields)
    for key in sorted(set(values) - known):
        close = difflib.get_close_matches(key, sorted(known), n=3, cutoff=0.6)
        suggestion = (
            f"rename it to {' or '.join(repr(name) for name in close)}"
            if close
            else "remove it, or move the note into the brandbook"
        )
        issues.append(
            MigrationIssue(
                field=f"{prefix}{key}",
                value=values[key],
                reason="the executable contract has no such field",
                instruction=f"{suggestion}; an unknown key is never ignored silently",
            )
        )


def _check_choices(migrated: dict[str, Any], issues: list[MigrationIssue]) -> None:
    _check_choice_block(migrated, ProjectVideoConfig, "", issues)
    style = migrated.get("caption_style")
    if isinstance(style, dict):
        _check_choice_block(style, CaptionConfig, "caption_style.", issues)


def _check_choice_block(
    values: dict[str, Any],
    model: type[BaseModel],
    prefix: str,
    issues: list[MigrationIssue],
) -> None:
    for name, field in model.model_fields.items():
        # schema_version is a choice too, but it has its own dedicated message.
        if name not in values or f"{prefix}{name}" == "schema_version":
            continue
        allowed = _choices(field.annotation)
        if not allowed:
            continue
        value = values[name]
        if value is None or value in allowed:
            continue
        canonical = _canonical(value, allowed)
        if canonical is not None:
            values[name] = canonical
            continue
        qualified = f"{prefix}{name}"
        detail = FIELD_GUIDANCE.get(qualified)
        allowed_text = ", ".join(repr(choice) for choice in allowed)
        issues.append(
            MigrationIssue(
                field=qualified,
                value=value,
                reason="a descriptive value is no longer accepted here",
                instruction=(f"choose one of: {allowed_text}" + (f"; {detail}" if detail else "")),
            )
        )


def _choices(annotation: Any) -> tuple[Any, ...]:
    """Allowed scalar values of a Literal, an Enum, or their optional form."""
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return tuple(member.value for member in annotation)
    origin = get_origin(annotation)
    if origin is Literal:
        return get_args(annotation)
    if origin is not None:
        collected: list[Any] = []
        for argument in get_args(annotation):
            if argument is type(None):
                continue
            collected.extend(_choices(argument))
        return tuple(collected)
    return ()


def _canonical(value: Any, allowed: tuple[Any, ...]) -> Any | None:
    """Same value in a different YAML scalar shape; never a different value."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        text = str(int(value)) if float(value).is_integer() else str(value)
        return text if text in allowed else None
    if isinstance(value, str):
        folded = value.strip().casefold()
        return next(
            (
                choice
                for choice in allowed
                if isinstance(choice, str) and choice.casefold() == folded
            ),
            None,
        )
    return None


def _check_ratios(migrated: dict[str, Any], issues: list[MigrationIssue]) -> None:
    for name, guidance in RATIO_GUIDANCE.items():
        if name not in migrated:
            continue
        value = migrated[name]
        if value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)):
            continue
        issues.append(
            MigrationIssue(
                field=name,
                value=value,
                reason="this is now a rendered amount, not a description",
                instruction=f"write a number between 0 and 1: {guidance}",
            )
        )


def _check_percentages(migrated: dict[str, Any], issues: list[MigrationIssue]) -> None:
    margins = migrated.get("safe_margins")
    candidates: list[tuple[str, Any]] = []
    if isinstance(margins, dict):
        candidates.extend((f"safe_margins.{edge}", value) for edge, value in margins.items())
    style = migrated.get("caption_style")
    for qualified in PERCENT_FIELDS:
        block, _, name = qualified.partition(".")
        if block == "caption_style" and isinstance(style, dict) and name in style:
            candidates.append((qualified, style[name]))
    for field, value in candidates:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if not 0 < value < 1:
            continue
        issues.append(
            MigrationIssue(
                field=field,
                value=value,
                reason=(
                    "margins used to be fractions of the frame and are now "
                    f"percentages, so {value!r} renders as {value:g}% instead of "
                    f"{value * 100:g}%"
                ),
                instruction=(
                    f"write {value * 100:g} to keep today's framing, or 0 to remove "
                    "the margin; this is a visible change, so it is not rescaled "
                    "for you"
                ),
            )
        )


def _check_font_family(migrated: dict[str, Any], issues: list[MigrationIssue]) -> None:
    font = migrated.get("font")
    if not isinstance(font, str) or not _looks_like_font_path(font):
        return
    issues.append(
        MigrationIssue(
            field="font",
            value=font,
            reason="`font` is now the family name that the renderer asks for by name",
            instruction=(
                f"set `font_file: {font}` and set `font` to the family that file "
                "provides, so a missing file fails loudly instead of falling back"
            ),
        )
    )


def _looks_like_font_path(value: str) -> bool:
    return (
        "/" in value
        or "\\" in value
        or value.casefold().endswith((".ttf", ".otf", ".woff", ".woff2"))
    )


def _format(issues: list[MigrationIssue], source: str | None) -> str:
    where = f" {source}" if source else ""
    return "\n".join(
        [
            f"project video config{where} still holds pre-0.4 values; "
            f"{len(issues)} field(s) need a decision.",
            "Nothing was converted automatically: each of these changes how the edit "
            "looks or sounds.",
            f"Fix them, then rerun `social-video-agent config validate`. See {MIGRATION_DOC}.",
            "",
            *(issue.render() for issue in issues),
        ]
    )
