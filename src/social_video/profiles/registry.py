"""Finding and loading profiles."""

from __future__ import annotations

import json
from pathlib import Path

from social_video.errors import ValidationError
from social_video.paths import app_home
from social_video.schemas.brand import BrandProfile, OutputProfile
from social_video.schemas.platform import PlatformSpec

_BUILTIN = Path(__file__).parent / "data"


def _search_paths(kind: str, extra: Path | None) -> list[Path]:
    """Later entries win, so a user profile overrides a built-in one."""
    paths = [_BUILTIN / kind, app_home() / kind]
    if extra is not None:
        paths.append(extra)
    return paths


def _find(name: str, kind: str, extra: Path | None) -> Path:
    tried: list[Path] = []
    for directory in reversed(_search_paths(kind, extra)):
        candidate = directory / f"{name}.json"
        tried.append(candidate)
        if candidate.is_file():
            return candidate
    known = ", ".join(_names(kind, extra)) or "<none>"
    raise ValidationError(
        f"no {kind[:-1]} named {name!r}. Available: {known}\n"
        f"Looked in: {', '.join(str(t.parent) for t in tried)}"
    )


def _names(kind: str, extra: Path | None = None) -> list[str]:
    found: set[str] = set()
    for directory in _search_paths(kind, extra):
        if directory.is_dir():
            found.update(p.stem for p in directory.glob("*.json"))
    return sorted(found)


def available_profiles(extra: Path | None = None) -> list[str]:
    return _names("profiles", extra)


def available_brands(extra: Path | None = None) -> list[str]:
    return _names("brands", extra)


def available_platforms(extra: Path | None = None) -> list[str]:
    return _names("platforms", extra)


def load_platform(name: str, extra: Path | None = None) -> PlatformSpec:
    path = _find(name, "platforms", extra)
    return _load(PlatformSpec, path)


def load_profile(name: str, extra: Path | None = None) -> OutputProfile:
    path = _find(name, "profiles", extra)
    return _load(OutputProfile, path)


def load_brand(name: str, extra: Path | None = None) -> BrandProfile:
    path = _find(name, "brands", extra)
    return _load(BrandProfile, path)


def _load(model, path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} is not valid JSON: {exc}") from exc
    try:
        return model.model_validate(data)
    except Exception as exc:
        raise ValidationError(f"{path} is not a valid {model.__name__}:\n  {exc}") from exc
