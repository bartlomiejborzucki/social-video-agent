"""Hook variants to test, and one sheet to review every piece of motion."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from social_video.errors import ValidationError
from social_video.ffmpeg.run import find_binary
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
    verdicts: Callable[[list[tuple[float, str]]], list[str]] | None = None,
) -> Path:
    """One labelled frame per graphic, punch-in and transition, in a grid.

    With ``verdicts``, each tile's label bar is coloured by what motion QA
    found at that moment: green clear, amber a warning, red an error.
    """
    from PIL import Image, ImageDraw

    moments = review_moments(plan, extra)
    if not moments:
        raise ValidationError("the motion plan has nothing to review")
    colours = {"ok": (24, 120, 60), "warning": (190, 120, 0), "error": (170, 30, 30)}
    found = verdicts(moments) if verdicts is not None else ["none"] * len(moments)
    frames: list[Image.Image] = []
    work = output.with_suffix(".frames")
    work.mkdir(parents=True, exist_ok=True)
    try:
        for index, (at, label) in enumerate(moments):
            still = work / f"{index:03d}.png"
            subprocess.run(
                [find_binary("ffmpeg"), "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(video),
                 "-frames:v", "1", "-vf", f"scale={tile_width}:-2", str(still)],
                check=True, timeout=120,
            )  # fmt: skip
            with Image.open(still) as image:
                tile = image.convert("RGB")
            draw = ImageDraw.Draw(tile)
            bar = colours.get(found[index], (0, 0, 0))
            draw.rectangle((0, 0, tile.width, 26), fill=bar)
            draw.text((6, 6), f"{at:5.2f}s  {label}", fill=(255, 255, 255))
            if found[index] in colours:
                draw.rectangle((0, 0, tile.width - 1, tile.height - 1), outline=bar, width=3)
            frames.append(tile)
    finally:
        for leftover in work.glob("*.png"):
            leftover.unlink()
        work.rmdir()
    columns = min(4, len(frames))
    rows = -(-len(frames) // columns)
    height = frames[0].height
    sheet = Image.new(
        "RGB", (columns * tile_width + (columns - 1) * 4, rows * height + (rows - 1) * 4)
    )
    for index, frame in enumerate(frames):
        sheet.paste(
            frame, ((index % columns) * (tile_width + 4), (index // columns) * (height + 4))
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return output
