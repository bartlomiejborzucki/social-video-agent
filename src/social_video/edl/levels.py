"""One level for every recording's speech in an edit.

Loudness is normalised once, over the whole mix, with one gain. That brings
the edit to its target and leaves the recordings exactly as far apart as they
were: a question recorded close to the microphone and an answer recorded
across a room stay two levels, and the viewer rides the volume. Here each
recording's speech is measured on its own and moved toward the level they
share, weighted by how long each is heard, inside a ceiling. A single
recording, or recordings already together, are left alone.

The gains are applied at render and recorded in the render manifest; the EDL
is not changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from social_video.schemas.edl import EDL

#: The most a recording's speech is moved, either way.
MAX_LEVEL_GAIN_DB = 6.0
#: A move smaller than this is not worth making.
MIN_LEVEL_GAIN_DB = 0.5
#: Recordings this close together after levelling count as one level.
LEVEL_TOLERANCE_LU = 1.5
#: Speech shorter than this is not measured: the reading would be noise.
MIN_SPEECH_S = 1.0


@dataclass(frozen=True)
class SpeechLevels:
    """What each recording's speech measured, and the gain it gets."""

    measured: dict[str, float] = field(default_factory=dict)
    gains: dict[str, float] = field(default_factory=dict)
    target: float | None = None

    @property
    def changed(self) -> bool:
        return bool(self.gains)

    @property
    def spread_after(self) -> float:
        """How far apart the recordings still are once the gains are applied."""
        after = [level + self.gains.get(name, 0.0) for name, level in self.measured.items()]
        return max(after) - min(after) if len(after) > 1 else 0.0

    def reason(self) -> str:
        moved = ", ".join(f"{name} {gain:+.1f} dB" for name, gain in sorted(self.gains.items()))
        return f"speech levelled between recordings ({moved})"

    def evidence(self) -> dict[str, object]:
        return {
            "measured_lufs": {name: round(v, 1) for name, v in sorted(self.measured.items())},
            "gain_db": {name: round(v, 1) for name, v in sorted(self.gains.items())},
            "target_lufs": None if self.target is None else round(self.target, 1),
            "spread_after_lu": round(self.spread_after, 1),
            "max_gain_db": MAX_LEVEL_GAIN_DB,
        }

    def applied_to(self, edl: EDL) -> EDL:
        """The edit with each range carrying its recording's gain, for this render."""
        if not self.gains:
            return edl
        ranges = [
            rng.model_copy(
                update={
                    "audio_gain_db": round(
                        rng.audio_gain_db + self.gains.get(rng.effective_audio_source, 0.0), 2
                    )
                }
            )
            for rng in edl.ranges
        ]
        return edl.model_copy(update={"ranges": ranges})


NO_LEVELS = SpeechLevels()


def plan_levels(measured: dict[str, float], seconds: dict[str, float]) -> SpeechLevels:
    """Decide each recording's gain from the levels of them all.

    The target is their level weighted by how long each is heard, so the
    recording that carries the edit moves least.
    """
    if len(measured) < 2:
        return SpeechLevels(measured=dict(measured))
    total = sum(seconds.get(name, 0.0) for name in measured)
    if total <= 0:
        return SpeechLevels(measured=dict(measured))
    target = sum(level * seconds.get(name, 0.0) for name, level in measured.items()) / total
    gains = {}
    for name, level in measured.items():
        gain = max(-MAX_LEVEL_GAIN_DB, min(MAX_LEVEL_GAIN_DB, target - level))
        if abs(gain) >= MIN_LEVEL_GAIN_DB:
            gains[name] = round(gain, 2)
    return SpeechLevels(measured=dict(measured), gains=gains, target=target)
