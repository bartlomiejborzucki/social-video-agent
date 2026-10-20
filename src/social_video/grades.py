"""Named looks a range or a whole edit can be graded with.

A grade is a name, not a filter string: the EDL stays renderer-independent
and reviewable, and an unknown name is refused rather than ignored. Names can
be combined with ``+`` (``mono_contrast+shake``) and are applied in the order
written. The FFmpeg render draws them, and the Remotion route composites over
that render, so both renderers show the same look.
"""

from __future__ import annotations

from collections.abc import Callable

#: Shake: how far the frame drifts, as a share of the canvas, and how much it
#: is enlarged so the drifting edge never shows.
SHAKE_MARGIN = 0.04


def _mono(_canvas: tuple[int, int]) -> str:
    return "hue=s=0"


def _mono_contrast(_canvas: tuple[int, int]) -> str:
    # Desaturate, then a harder S-curve: the "memory" look for a reaction shot.
    return "hue=s=0,eq=contrast=1.35:brightness=-0.03,curves=preset=increase_contrast"


def _shake(canvas: tuple[int, int]) -> str:
    """A handheld wobble: enlarge slightly, then move the crop on mixed sines.

    Deterministic, so a re-render is identical; the sum of the sine weights
    stays below one, so the crop never leaves the enlarged frame.
    """
    width, height = canvas
    big_w = round(width * (1 + 2 * SHAKE_MARGIN) / 2) * 2
    big_h = round(height * (1 + 2 * SHAKE_MARGIN) / 2) * 2
    x = "(iw-ow)/2*(1+0.55*sin(2*PI*t*2.3)+0.35*sin(2*PI*t*5.9+1.3))"
    y = "(ih-oh)/2*(1+0.5*sin(2*PI*t*1.7+0.4)+0.4*sin(2*PI*t*6.7+2.1))"
    return f"scale={big_w}:{big_h}:flags=bicubic,crop={width}:{height}:x='{x}':y='{y}'"


GRADES: dict[str, Callable[[tuple[int, int]], str]] = {
    "mono": _mono,
    "mono_contrast": _mono_contrast,
    "shake": _shake,
}


def grade_names(grade: str) -> list[str]:
    """The named looks in a grade string, refusing any this renderer cannot draw."""
    names = [part.strip() for part in grade.split("+") if part.strip()]
    unknown = [name for name in names if name not in GRADES]
    if unknown:
        raise ValueError(
            f"unknown grade {', '.join(repr(n) for n in unknown)}; "
            f"known: {', '.join(sorted(GRADES))} (combine with +)"
        )
    return names


def grade_filter(grade: str, canvas: tuple[int, int]) -> str | None:
    """The filter chain for a grade on a canvas of this size, or None for no grade."""
    names = grade_names(grade)
    if not names:
        return None
    # Scaling for the shake changes the sample aspect ratio; concat needs
    # every range at 1:1, like the ungraded ones.
    return ",".join(GRADES[name](canvas) for name in names) + ",setsar=1"
