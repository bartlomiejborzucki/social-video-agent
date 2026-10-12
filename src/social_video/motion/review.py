"""Hook variants to test, and one sheet to review every piece of motion."""

from __future__ import annotations

from pathlib import Path

from social_video.errors import ValidationError
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan


def with_hook(plan: MotionPlan, text: str, *, end: float = 1.8) -> MotionPlan:
    """The plan with its hook card saying ``text`` (one is added if there is none)."""
    elements = list(plan.elements)
    for index, element in enumerate(elements):
        if element.type is MotionElementType.HOOK_CARD:
            elements[index] = element.model_copy(update={"text": text})
            break
    else:
        elements.insert(
            0,
            MotionElement(
                type=MotionElementType.HOOK_CARD, start=0.0, end=end, text=text,
                reason="Hook variant for testing which opening holds viewers.",
            ),
        )  # fmt: skip
    return MotionPlan.model_validate(plan.model_copy(update={"elements": elements}).model_dump())


def review_moments(
    plan: MotionPlan, extra: list[tuple[float, str]] | None = None
) -> list[tuple[float, str]]:
    """Where each piece of motion is at its fullest, with a label.

    ``extra`` adds moments the plan no longer holds, such as Claude Motion
    segments that replaced a graphic.
    """
    moments: list[tuple[float, str]] = list(extra or [])
    for element in plan.elements:
        moments.append(
            (element.start + min(0.6, (element.end - element.start) * 0.5), element.type.value)
        )
    for punch in plan.punch_ins:
        moments.append(((punch.start + punch.end) / 2, f"punch-in {punch.scale:g}"))
    for transition in plan.transitions:
        moments.append((transition.at, f"{transition.style.value} transition"))
    return sorted(moments)


def motion_sheet(
    video: Path,
    plan: MotionPlan,
    output: Path,
    *,
    tile_width: int = 270,
    extra: list[tuple[float, str]] | None = None,
) -> Path:
    """One labelled frame per graphic, punch-in and transition, in a grid."""
    from social_video.imaging import contact_sheet

    moments = review_moments(plan, extra)
    if not moments:
        raise ValidationError("the motion plan has nothing to review")
    return contact_sheet(video, moments, output, tile_width=tile_width)
