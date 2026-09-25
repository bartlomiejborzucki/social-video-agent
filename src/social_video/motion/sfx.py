"""Sound under the motion: whooshes on transitions, pops on graphics.

The files come from the user's own library -- the tool never sources or clears
audio -- and are chosen by name: `whoosh`/`swoosh`/`transition` for a
transition, `pop`/`click`/`ding`/`tick` for a graphic entering, `hit`/`boom`/
`impact` for the hook card. Each lands exactly when its visual starts, a few
decibels under the voice, as an ordinary licensed sound effect in the EDL.
"""

from __future__ import annotations

from pathlib import Path

from social_video.errors import ValidationError
from social_video.schemas.edl import EDL, SoundEffect
from social_video.schemas.motion import MotionElementType, MotionPlan

AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
ROLES = {
    "transition": ("whoosh", "swoosh", "swish", "transition"),
    "graphic": ("pop", "click", "ding", "tick", "blip"),
    "hook": ("hit", "boom", "impact", "riser"),
}


def library(directory: Path) -> dict[str, list[Path]]:
    files = sorted(p for p in directory.rglob("*") if p.suffix.casefold() in AUDIO)
    return {
        role: [p for p in files if any(word in p.stem.casefold() for word in words)]
        for role, words in ROLES.items()
    }


def sync_sfx(
    edl: EDL, plan: MotionPlan, directory: Path, *, gain_db: float = -10.0
) -> tuple[EDL, list[SoundEffect]]:
    """Place one effect per transition and graphic, from the user's library."""
    if not directory.is_dir():
        raise ValidationError(f"no sound library at {directory}")
    found = library(directory)
    if not any(found.values()):
        names = ", ".join(sorted({w for words in ROLES.values() for w in words}))
        raise ValidationError(f"no usable effects in {directory}; name files with one of: {names}")
    placed = {round(effect.at, 2) for effect in edl.sound_effects}
    added: list[SoundEffect] = []
    turn = {role: 0 for role in ROLES}

    def pick(role: str) -> Path | None:
        options = found[role] or found["graphic"] or found["transition"]
        if not options:
            return None
        choice = options[turn[role] % len(options)]
        turn[role] += 1
        return choice

    moments: list[tuple[float, str, str]] = [
        (t.at - t.duration / 2, "transition", f"{t.style.value} transition at {t.at:.2f}s")
        for t in plan.transitions
    ]
    for element in plan.elements:
        role = "hook" if element.type is MotionElementType.HOOK_CARD else "graphic"
        if element.type is MotionElementType.PROGRESS:
            continue
        moments.append(
            (element.start, role, f"{element.type.value} entering at {element.start:.2f}s")
        )
    for at, role, why in sorted(moments):
        at = max(0.0, round(at, 3))
        if round(at, 2) in placed:
            continue
        path = pick(role)
        if path is None:
            continue
        effect = SoundEffect(
            path=str(path.resolve()), at=at, gain_db=gain_db, license_confirmed=True,
            reason=f"Synced to the {why}.",
        )  # fmt: skip
        added.append(effect)
        placed.add(round(at, 2))
    updated = edl.model_copy(update={"sound_effects": [*edl.sound_effects, *added]})
    return EDL.model_validate(updated.model_dump()), added
