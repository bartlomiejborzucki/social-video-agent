"""Apply the supervising editor's explicit QA handoff without re-analysis."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from social_video.errors import ValidationError
from social_video.schemas.editorial_qa import EditorialQA, EditorialQAStatus
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
        _set_path(payload, fix.path, fix.value)
    try:
        return EDL.model_validate(payload), True
    except Exception as exc:
        raise ValidationError(f"editorial fixes do not produce a valid EDL: {exc}") from exc


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
