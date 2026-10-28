"""Sound under the motion: whooshes on transitions, pops on graphics.

The files come from a local folder, or from the built-in set (a few CC0
effects listed by `@remotion/sfx`, downloaded once into the cache), and are
chosen by name: `whoosh`/`swoosh`/
`transition` for a transition, `pop`/`click`/`ding`/`tick` for a graphic
entering, `hit`/`boom`/`impact` for the hook card. Each lands exactly when its visual starts, a few
decibels under the voice, as an ordinary sound effect in the EDL.
"""

from __future__ import annotations

from pathlib import Path

from social_video.errors import SocialVideoError, ValidationError
from social_video.schemas.edl import EDL, SoundEffect
from social_video.schemas.motion import MotionElementType, MotionPlan

AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
ROLES = {
    "transition": ("whoosh", "swoosh", "swish", "transition"),
    "graphic": ("pop", "click", "ding", "tick", "blip"),
    "hook": ("hit", "boom", "impact", "riser"),
}


#: Neutral CC0 effects from `@remotion/sfx` 4.0.538, renamed so ROLES finds
#: them. Meme sounds in that package quote other works and are left out, as is
#: `ding`, which is not released under a free licence.
BUILTIN = {
    "whoosh.wav": (
        "https://remotion.media/whoosh.wav",
        "d98f010fa5f03fd3f4f77418f8ba6a962d36e63357265772771c4ac69c1a63a7",
    ),
    "swoosh-whip.wav": (
        "https://remotion.media/whip.wav",
        "8713e68578c7f579bdfc24ff77fd3e3eefc1a9b5d1232a63c10800b81d0ead5f",
    ),
    "click-mouse.wav": (
        "https://remotion.media/mouse-click.wav",
        "887a9259203cafa24ad90274029d574ba29438bcdc87e6f384e4472f85736348",
    ),
}


def builtin_library(directory: Path | None = None) -> Path:
    """The built-in effects, downloaded once and checked against their hashes."""
    import hashlib
    import urllib.request

    from social_video.fsutil import atomic_write_bytes
    from social_video.paths import app_home

    target = directory or app_home() / "sfx" / "remotion-sfx-4.0.538"
    target.mkdir(parents=True, exist_ok=True)
    for name, (url, sha256) in BUILTIN.items():
        path = target / name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256:
            continue
        try:
            # The host refuses urllib's default User-Agent.
            request = urllib.request.Request(url, headers={"User-Agent": "social-video-agent"})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
        except OSError as exc:
            raise SocialVideoError(f"could not download the built-in effect {url}: {exc}") from exc
        if hashlib.sha256(data).hexdigest() != sha256:
            raise SocialVideoError(f"the built-in effect {url} does not match its pinned hash")
        atomic_write_bytes(path, data)
    return target


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
        if element.type is MotionElementType.STRIKE:
            crossed, _replaced = element.strike_moments
            moments.append((crossed, "graphic", f"strike crossing out at {crossed:.2f}s"))
    for at, role, why in sorted(moments):
        at = max(0.0, round(at, 3))
        if round(at, 2) in placed:
            continue
        path = pick(role)
        if path is None:
            continue
        effect = SoundEffect(
            path=str(path.resolve()), at=at, gain_db=gain_db,
            reason=f"Synced to the {why}.",
        )  # fmt: skip
        added.append(effect)
        placed.add(round(at, 2))
    updated = edl.model_copy(update={"sound_effects": [*edl.sound_effects, *added]})
    return EDL.model_validate(updated.model_dump()), added
