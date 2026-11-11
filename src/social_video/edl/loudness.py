"""Loudness measurement and normalisation.

Normalisation is decided from a measurement, not applied blindly. Two reasons:

* ``loudnorm`` produces NaN on digitally silent input and the encoder then
  fails outright, so a perfectly reasonable edit -- a short range that happens
  to fall in a quiet passage -- dies with an opaque error. Measuring first lets
  us skip normalisation when there is nothing to normalise.
* Single-pass ``loudnorm`` guesses; given measured values it hits the target.
  The measurement pass decodes audio only, with no scaling or video encoding,
  so it costs a fraction of the render it informs.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from social_video.errors import FFmpegError
from social_video.ffmpeg.filters import LOUDNORM_I, LOUDNORM_LRA, LOUDNORM_TP
from social_video.ffmpeg.run import run_ffmpeg

log = logging.getLogger(__name__)

#: Integrated loudness below which material is treated as silent.
SILENCE_LUFS = -60.0

_JSON_BLOCK = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


@dataclass(frozen=True)
class LoudnessMeasurement:
    input_i: float
    input_tp: float
    input_lra: float
    input_thresh: float
    target_offset: float

    @property
    def is_silent(self) -> bool:
        """Whether there is anything here worth normalising."""
        import math

        return (
            math.isnan(self.input_i) or math.isinf(self.input_i) or (self.input_i <= SILENCE_LUFS)
        )


def measure_loudness(
    inputs: list[str], audio_graph: str, out_label: str
) -> LoudnessMeasurement | None:
    """Run the audio half of a render and report its loudness.

    Returns ``None`` when the measurement cannot be parsed, in which case the
    caller should fall back to single-pass normalisation rather than guessing.
    """
    graph = f"{audio_graph};{out_label}loudnorm=" + (
        f"I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}:print_format=json[m]"
    )
    try:
        stderr = run_ffmpeg(
            [
                *inputs,
                "-filter_complex",
                graph,
                "-map",
                "[m]",
                "-f",
                "null",
                "-",
            ],
            desc="measure output loudness",
            timeout=7200,
        )
    except FFmpegError as exc:
        # A measurement failure must never block a render; degrade instead.
        log.debug("loudness measurement failed: %s", exc)
        return None

    # loudnorm prints its summary at end of stream; take the last block.
    blocks = _JSON_BLOCK.findall(stderr)
    if not blocks:
        return None
    try:
        data = json.loads(blocks[-1])
        return LoudnessMeasurement(
            input_i=float(data["input_i"]),
            input_tp=float(data["input_tp"]),
            input_lra=float(data["input_lra"]),
            input_thresh=float(data["input_thresh"]),
            target_offset=float(data.get("target_offset", 0.0)),
        )
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        log.debug("could not parse loudnorm output: %s", exc)
        return None


#: The most the gain is raised to make up for what the limiter took off.
MAX_MAKEUP_DB = 3.0


def is_limited_gain(normaliser: str | None) -> bool:
    """Whether a normaliser is the gain-and-limiter form rather than ``loudnorm``."""
    return bool(normaliser) and not str(normaliser).startswith("loudnorm")


def loudnorm_filter(
    measurement: LoudnessMeasurement | None, *, makeup_db: float = 0.0
) -> str | None:
    """Build the normalisation filter, or ``None`` to skip it.

    With a measurement the whole mix gets one gain. Where that gain fits under
    the true-peak ceiling, ``loudnorm`` applies it in its linear mode. Where
    it does not -- speech recorded hot, a quiet edit that needs lifting --
    ``loudnorm`` would silently switch to its dynamic mode and ride the gain
    over time: the first seconds come out louder than the rest, and two
    speakers levelled a moment ago drift apart again. So there the gain is
    applied as it is and a limiter catches only the peaks above the ceiling.

    ``makeup_db`` raises that gain by what the limiter was measured to take
    off the loudness, up to ``MAX_MAKEUP_DB``, so the mix still reaches its
    target.

    Without a measurement it falls back to a single dynamic pass, which is
    approximate but better than nothing.
    """
    base = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
    if measurement is None:
        return base
    if measurement.is_silent:
        return None
    gain = LOUDNORM_I - measurement.input_i
    if measurement.input_tp + gain <= LOUDNORM_TP and measurement.input_lra <= LOUDNORM_LRA:
        return (
            f"{base}"
            f":measured_I={measurement.input_i:.2f}"
            f":measured_TP={measurement.input_tp:.2f}"
            f":measured_LRA={measurement.input_lra:.2f}"
            f":measured_thresh={measurement.input_thresh:.2f}"
            f":offset={measurement.target_offset:.2f}"
            f":linear=true"
        )
    ceiling = 10 ** (LOUDNORM_TP / 20.0)
    gain += min(MAX_MAKEUP_DB, max(0.0, makeup_db))
    return f"volume={gain:.2f}dB,alimiter=limit={ceiling:.4f}:attack=5:release=50:level=false"
