"""One decision -- calm, lively or bold -- sets how much a cut moves.

A short that never moves reads as a recording; one that moves on every beat
reads as a template. The energy level picks a point between the two for every
kind of movement at once, so the agent is not tuning five knobs to get a feel,
and the brand's limits still hold.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnergyPreset:
    name: str
    #: Largest zoom any punch-in or range may reach.
    punch_in_max: float
    #: Movement budget the brand profile reports (0 = none).
    motion_intensity: float
    #: Transitions allowed per minute of output.
    transitions_per_minute: float
    #: Accents (graphics, punch-ins) proposed per minute by `motion suggest`.
    accents_per_minute: float
    #: The caption animation this energy implies when the config names none.
    caption_animation: str
    #: Shortest gap between two proposed accents, in seconds.
    min_accent_gap: float


ENERGY: dict[str, EnergyPreset] = {
    "calm": EnergyPreset("calm", 1.12, 0.25, 0.0, 4.0, "none", 6.0),
    "lively": EnergyPreset("lively", 1.18, 0.6, 4.0, 10.0, "pop", 3.5),
    "bold": EnergyPreset("bold", 1.25, 0.9, 8.0, 16.0, "box", 2.5),
}

#: Visual families for the Remotion layer. Each takes the brand's colours and
#: font; the pack decides shapes, entrances and transitions.
STYLE_PACKS = ("editorial", "bold-social", "tech-minimal")


def energy_preset(name: str | None) -> EnergyPreset:
    return ENERGY.get((name or "calm").strip().casefold(), ENERGY["calm"])
