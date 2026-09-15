"""Smoothing a sequence of crop positions.

The combination that makes reframing look deliberate rather than nervous, and
that none of the open-source reframers surveyed implement together:

* a **dead zone**, so small subject movement does not move the frame at all;
* **exponential smoothing**, so movement that does happen is gradual;
* **hysteresis**, so the crop does not oscillate between two subjects who are
  roughly equally prominent.

clipsai contributes the dead-zone idea (it merges adjacent segments whose
positions differ by under 4% of the frame) but applies no smoothing, so its
crop is a step function. claude-shorts smooths its cursor path with a moving
average but leaves its face path completely static. Neither has hysteresis.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Movement below this fraction of the crop width is ignored entirely.
DEFAULT_DEAD_ZONE = 0.04
#: Exponential smoothing factor. Lower is calmer.
DEFAULT_ALPHA = 0.25
#: A new subject must beat the current one by this much before the crop moves.
DEFAULT_HYSTERESIS = 0.25


@dataclass
class SmoothingConfig:
    dead_zone: float = DEFAULT_DEAD_ZONE
    alpha: float = DEFAULT_ALPHA
    hysteresis: float = DEFAULT_HYSTERESIS


def smooth_positions(
    positions: list[float],
    *,
    span: float,
    config: SmoothingConfig | None = None,
) -> list[float]:
    """Smooth a series of crop positions.

    ``span`` is the crop width (or height), used to scale the dead zone so the
    same configuration behaves consistently at any resolution.

    The smoothing is **zero-phase**: an exponential filter is run forwards and
    then backwards over the series. A single forward pass is what a real-time
    tracker is forced to use, and it lags behind any sustained movement --
    visibly so, as the subject drifts toward the edge of frame and stays there.
    We are planning offline against a known future, so there is no reason to
    accept that lag. Running the filter in both directions cancels it while
    keeping the same calmness.

    The dead zone is applied *after* smoothing, so it gates the final motion
    rather than starving the filter of input.
    """
    if not positions:
        return []
    cfg = config or SmoothingConfig()
    if len(positions) == 1:
        return list(positions)

    # Pad both ends by linear extrapolation before filtering. Without padding
    # the two passes leave a residual offset at the first and last samples,
    # which in practice means the very start and very end of a clip -- exactly
    # the frames a viewer is most likely to notice.
    pad = _pad_length(cfg.alpha, len(positions))
    padded = _extrapolate(positions, pad)
    forward = _ema(padded, cfg.alpha)
    both = list(reversed(_ema(list(reversed(forward)), cfg.alpha)))
    backward = both[pad : len(both) - pad] if pad else both

    # Hold still until the target has moved beyond the dead zone, then follow.
    threshold = cfg.dead_zone * span
    out = [backward[0]]
    held = backward[0]
    for value in backward[1:]:
        if abs(value - held) >= threshold:
            held = value
        out.append(held)
    return out


def _pad_length(alpha: float, count: int) -> int:
    """Roughly three filter time constants, capped at the series length."""
    if alpha <= 0:
        return 0
    return max(0, min(count, int(3.0 / alpha)))


def _extrapolate(values: list[float], pad: int) -> list[float]:
    """Extend a series at both ends along its local trend.

    The slope is fitted by least squares over a window rather than taken from
    the two end samples: on noisy detections those two points give an
    essentially random slope, and extrapolating twelve steps along it injects a
    far larger excursion than the noise it was meant to smooth.
    """
    if pad <= 0 or len(values) < 2:
        return list(values)
    window = min(len(values), max(2, pad))
    head_slope = _fit_slope(values[:window])
    tail_slope = _fit_slope(values[-window:])
    head = [values[0] - head_slope * (pad - i) for i in range(pad)]
    tail = [values[-1] + tail_slope * (i + 1) for i in range(pad)]
    return head + list(values) + tail


def _fit_slope(values: list[float]) -> float:
    """Least-squares slope per sample over a short window."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    numerator = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    denominator = sum((i - mean_x) ** 2 for i in range(n))
    return numerator / denominator if denominator else 0.0


def _ema(values: list[float], alpha: float) -> list[float]:
    """Single-pass exponential moving average."""
    out = [values[0]]
    current = values[0]
    for value in values[1:]:
        current += alpha * (value - current)
        out.append(current)
    return out


def dedupe_keyframes(
    times: list[float], positions: list[float], *, span: float, dead_zone: float | None = None
) -> list[tuple[float, float]]:
    """Drop keyframes that do not move the crop meaningfully.

    Threshold expressed as a fraction of the crop dimension, following
    AgriciDaniel/claude-shorts (MIT), which is the right formulation: it makes
    the setting resolution independent.
    """
    if not times:
        return []
    threshold = (dead_zone if dead_zone is not None else DEFAULT_DEAD_ZONE) * span
    kept = [(times[0], positions[0])]
    for t, p in zip(times[1:], positions[1:], strict=True):
        if abs(p - kept[-1][1]) >= threshold:
            kept.append((t, p))
    return kept


def choose_with_hysteresis(
    scores: list[float], *, hysteresis: float = DEFAULT_HYSTERESIS
) -> list[int]:
    """Pick a winner per step, resisting a switch until it is clearly warranted.

    ``scores`` is one list of candidate scores per step. Without this, two
    people of similar prominence make the crop flip back and forth every time
    detection noise reorders them.
    """
    chosen: list[int] = []
    current = -1
    for step in scores:
        if not step:
            chosen.append(current)
            continue
        best = max(range(len(step)), key=lambda i: step[i])
        unset = current < 0 or current >= len(step)
        # Switch only when the challenger is clearly better, not merely ahead.
        clearly_better = (
            not unset and best != current and step[best] > step[current] * (1.0 + hysteresis)
        )
        if unset or clearly_better:
            current = best
        chosen.append(current)
    return chosen
