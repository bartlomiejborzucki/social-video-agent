"""Shared artifact plumbing: versioning, and UTF-8-safe load/save."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from social_video.errors import ValidationError

#: Bumped when a change to any artifact shape is not backwards compatible.
SCHEMA_VERSION = 1


class Artifact(BaseModel):
    """Base for every artifact that is written to disk."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: int = Field(
        default=SCHEMA_VERSION,
        description="Artifact schema version. Mismatch is reported, never guessed at.",
    )

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


T = TypeVar("T", bound=Artifact)


def save_artifact(artifact: Artifact, path: str | Path) -> Path:
    """Write an artifact as UTF-8 JSON, creating parent directories.

    ``encoding="utf-8"`` is not optional. Upstream omits it in three places
    (``render.py:375``, ``render.py:487``, ``transcribe.py:180``) and has
    already had to fix the same bug once elsewhere; on a Windows console with a
    legacy code page it raises UnicodeEncodeError mid-render, after the work is
    done.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(artifact.to_json(), encoding="utf-8")
    tmp.replace(p)  # atomic, so an interrupted write never truncates a good file
    return p


def load_artifact(model: type[T], path: str | Path) -> T:
    """Read and validate an artifact, reporting the exact field that is wrong."""
    p = Path(path)
    if not p.is_file():
        raise ValidationError(f"{model.__name__} not found at {p}")
    try:
        raw: Any = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"{p} is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from exc

    if isinstance(raw, dict):
        found = raw.get("schema_version")
        if found is not None and found != SCHEMA_VERSION:
            raise ValidationError(
                f"{p} has schema_version {found}, but this build of social-video-agent "
                f"writes and reads version {SCHEMA_VERSION}. Regenerate the artifact "
                f"rather than editing the version by hand."
            )
    try:
        return model.model_validate(raw)
    except PydanticValidationError as exc:
        lines = [f"{p} does not match the {model.__name__} schema:"]
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"]) or "<root>"
            lines.append(f"  {loc}: {err['msg']}")
        raise ValidationError("\n".join(lines)) from exc
