"""Apply the supervising editor's explicit QA handoff without re-analysis."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from social_video.errors import ValidationError
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.config import BrandContract
from social_video.schemas.editorial_qa import EditorialArtifact, EditorialQA, EditorialQAStatus
from social_video.schemas.edl import EDL

_PATH_PART = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[([0-9]+)\])?")


def apply_editorial_qa(edl: EDL, review: EditorialQA) -> tuple[EDL, bool]:
    """Apply exactly ``review.fixes`` and nothing else.

    Approval is an explicit no-op. Each requested path is resolved against the
    serialized EDL, then the complete result is validated before it can replace
    the existing artifact.
    """
    if review.status is EditorialQAStatus.APPROVED:
        return edl, False

    payload = deepcopy(edl.model_dump(mode="json"))
    for fix in review.fixes:
        if fix.artifact is not EditorialArtifact.EDL:
            raise ValidationError(
                "this review changes captions/style; use apply_editorial_qa_artifacts"
            )
        _set_path(payload, fix.path, fix.value)
    try:
        return EDL.model_validate(payload), True
    except Exception as exc:
        raise ValidationError(f"editorial fixes do not produce a valid EDL: {exc}") from exc


def apply_editorial_qa_artifacts(
    edl: EDL,
    review: EditorialQA,
    *,
    captions: CaptionTrack | None = None,
    style: BrandContract | None = None,
) -> tuple[EDL, CaptionTrack | None, BrandContract | None, bool]:
    """Validate every target and result before returning any changed artifact."""
    if review.status is EditorialQAStatus.APPROVED:
        return edl, captions, style, False
    models = {
        EditorialArtifact.EDL: (edl, EDL),
        EditorialArtifact.CAPTIONS: (captions, CaptionTrack),
        EditorialArtifact.STYLE: (style, BrandContract),
    }
    payloads: dict[EditorialArtifact, dict[str, Any]] = {}
    for fix in review.fixes:
        current, _ = models[fix.artifact]
        if current is None:
            raise ValidationError(f"editorial fix targets missing {fix.artifact.value} artifact")
        payload = payloads.setdefault(fix.artifact, deepcopy(current.model_dump(mode="json")))
        _set_path(payload, fix.path, fix.value)
    validated: dict[EditorialArtifact, Any] = {}
    try:
        for artifact, payload in payloads.items():
            model_cls: Any = models[artifact][1]
            validated[artifact] = model_cls.model_validate(payload)
    except Exception as exc:
        raise ValidationError(
            f"editorial fixes are not atomic because validation failed: {exc}"
        ) from exc
    return (
        validated.get(EditorialArtifact.EDL, edl),
        validated.get(EditorialArtifact.CAPTIONS, captions),
        validated.get(EditorialArtifact.STYLE, style),
        bool(validated),
    )


def _set_path(payload: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    if not parts or any(not part for part in parts):
        raise ValidationError(f"invalid editorial fix path: {path!r}")

    current: Any = payload
    for position, raw in enumerate(parts):
        match = _PATH_PART.fullmatch(raw)
        if match is None:
            raise ValidationError(f"invalid editorial fix path: {path!r}")
        key, index_text = match.groups()
        if not isinstance(current, dict) or key not in current:
            raise ValidationError(f"editorial fix path does not exist: {path!r}")
        last = position == len(parts) - 1
        if index_text is None:
            if last:
                current[key] = value
            else:
                current = current[key]
            continue

        sequence = current[key]
        index = int(index_text)
        if not isinstance(sequence, list) or index >= len(sequence):
            raise ValidationError(f"editorial fix path does not exist: {path!r}")
        if last:
            sequence[index] = value
        else:
            current = sequence[index]
