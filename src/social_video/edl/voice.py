"""Measured voice cleanup: repair what a recording actually has, nothing else.

A one-button "enhance voice" applies the same chain to every clip: denoise,
EQ, compress, brighten. On a recording that did not need it that is not an
improvement, it is a different voice -- pumping where the speaker paused, a
lisp where the de-esser guessed, and the room ambience replaced by a faint
warble. The point of this module is that every filter has to be justified by a
measurement of *this* recording, and that each one has a ceiling low enough to
stay inside what the microphone heard.

What is measured, in one cheap audio-only pass per question:

* the per-window RMS distribution, so the noise floor is the 10th percentile
  and speech is the 90th. Their difference is the usable signal-to-noise ratio,
  which is what decides whether broadband denoising is warranted at all;
* energy below 60 Hz, which is handling noise, traffic and desk thumps rather
  than voice: no human fundamental lives there;
* energy in a narrow band at 50 and 60 Hz, which is mains hum. A tone
  concentrates its energy, so a narrow band that is *not* far below the broad
  low band is a hum rather than rumble;
* energy from 5 to 9 kHz relative to the whole signal, which is sibilance;
* peak level and flat factor, which show clipping. Clipping is reported and
  never "repaired": reconstructing a flattened waveform is invention.

Thresholds were calibrated against synthetic fixtures with a known defect and
against the same material without it. The numbers in the constants below are
the measured separation, not taste.

Order of the chain, which matters: remove what should not be there (rumble,
hum) before measuring loudness against it, denoise before compression so the
compressor does not pull the noise floor up, and de-ess before compression for
the same reason. Loudness normalisation stays where it was, at the very end.
"""

from __future__ import annotations

import logging
import math
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from social_video.ffmpeg.filters import escape_filter_path
from social_video.ffmpeg.run import run_ffmpeg

log = logging.getLogger(__name__)

#: Analysis window. Long enough to be a stable RMS, short enough that a pause
#: between sentences lands in its own window.
WINDOW_SAMPLES = 4800
#: Never analyse more than this; the first minutes describe the room.
MAX_ANALYSIS_SECONDS = 180.0

#: Below this signal-to-noise ratio (speech p90 minus floor p10) a recording
#: has audible broadband noise. Calibrated: clean speech with pauses measured
#: 28 dB, the same speech with white noise at -40 dBFS measured 11 dB.
NOISE_SNR_DB = 20.0
#: ...but only when the floor is actually audible. A quiet floor has nothing
#: worth removing, whatever the ratio says.
NOISE_FLOOR_DB = -55.0
#: Hard ceiling on denoising. ffmpeg's default is 12 dB, which on speech is
#: already audible as a warble on the tails of words.
MAX_NOISE_REDUCTION_DB = 10.0
MIN_NOISE_REDUCTION_DB = 4.0

#: Energy below 60 Hz, relative to the whole signal, that counts as rumble.
#: Calibrated: a voice with a 90 Hz fundamental measured -20.4 dB, the same
#: voice over a 45 Hz rumble measured -12.8 dB.
RUMBLE_RELATIVE_DB = -15.0
#: High-pass corner. Two poles at 80 Hz takes about 3 dB at 80 Hz and 12 dB at
#: 40 Hz: it removes the thump and leaves the lowest male fundamentals alone.
HIGHPASS_HZ = 80
HIGHPASS_POLES = 2

#: A narrow mains band this close to the whole signal is a hum.
HUM_RELATIVE_DB = -18.0
#: A tone concentrates energy, so its narrow band sits at or above the broad
#: low band. Broadband rumble spreads it, so its narrow band sits well below.
#: Calibrated: hum measured +2.0 dB against the low band, rumble -3.5 dB.
HUM_OVER_RUMBLE_DB = -1.5
#: Only the fundamental is notched. Notching the harmonics at 100/120 Hz thins
#: the voice, which is exactly the artificial result this avoids.
HUM_NOTCH_GAIN_DB = -15.0
HUM_NOTCH_WIDTH_HZ = 8.0

#: 5-9 kHz energy, relative to the whole signal, that counts as hot sibilance.
#: Calibrated: ordinary speech -16.8 dB, tape hiss -10.6 dB, hot esses -2.0 dB.
#: The threshold sits between hiss and esses so hiss is denoised, not de-essed.
SIBILANCE_RELATIVE_DB = -8.0
#: Gentle. ffmpeg's de-esser at full intensity audibly lisps.
DEESSER_INTENSITY = 0.15
DEESSER_MAX = 0.4

#: Loudness range above which speech is worth evening out at all. EBU R128
#: LRA; conversational speech recorded well sits around 6-10 LU.
WIDE_LRA_LU = 12.0
#: Ceiling on compression. Above about 2.5:1 speech starts to sound managed.
MAX_COMPRESSION_RATIO = 2.0
COMPRESSOR_THRESHOLD_DB = -18.0
COMPRESSOR_ATTACK_MS = 20
COMPRESSOR_RELEASE_MS = 250

#: Peak at or above this is treated as clipped, and only reported.
CLIPPING_PEAK_DB = -0.1

_RMS_LINE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?\d+(?:\.\d+)?|-?inf|nan)")
_STAT_LINE = re.compile(r"^\[Parsed_astats.*?\]\s*(?P<key>[A-Za-z ]+?):\s*(?P<value>\S+)\s*$")


@dataclass(frozen=True)
class VoiceMeasurement:
    """What this recording's speech actually measures."""

    speech_level_db: float
    noise_floor_db: float
    peak_db: float
    flat_factor: float
    low_band_relative_db: float
    hum_50_relative_db: float
    hum_60_relative_db: float
    sibilance_relative_db: float
    loudness_range_lu: float | None = None
    windows: int = 0

    @property
    def snr_db(self) -> float:
        return self.speech_level_db - self.noise_floor_db

    @property
    def clipped(self) -> bool:
        return self.peak_db >= CLIPPING_PEAK_DB

    def as_dict(self) -> dict[str, float | int | bool | None]:
        return {
            "speech_level_db": round(self.speech_level_db, 1),
            "noise_floor_db": round(self.noise_floor_db, 1),
            "snr_db": round(self.snr_db, 1),
            "peak_db": round(self.peak_db, 1),
            "flat_factor": round(self.flat_factor, 3),
            "low_band_relative_db": round(self.low_band_relative_db, 1),
            "hum_50_relative_db": round(self.hum_50_relative_db, 1),
            "hum_60_relative_db": round(self.hum_60_relative_db, 1),
            "sibilance_relative_db": round(self.sibilance_relative_db, 1),
            "loudness_range_lu": (
                None if self.loudness_range_lu is None else round(self.loudness_range_lu, 1)
            ),
            "analysis_windows": self.windows,
            "clipped": self.clipped,
        }


@dataclass(frozen=True)
class CleanupStep:
    """One decision, with the measurement that drove it either way."""

    name: str
    applied: bool
    reason: str
    filter: str = ""
    detail: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceCleanup:
    """The chain to apply, and the record of why each part is in or out."""

    steps: tuple[CleanupStep, ...]
    measurement: VoiceMeasurement | None

    @property
    def filters(self) -> tuple[str, ...]:
        return tuple(step.filter for step in self.steps if step.applied and step.filter)

    @property
    def chain(self) -> str | None:
        return ",".join(self.filters) or None

    @property
    def changed(self) -> bool:
        return bool(self.filters)

    def evidence(self) -> dict[str, object]:
        """What the render manifest records, so QA checks facts not intent."""
        return {
            "changed": self.changed,
            "chain": self.chain or "",
            "applied": [
                {"name": step.name, "reason": step.reason, "filter": step.filter, **step.detail}
                for step in self.steps
                if step.applied
            ],
            "skipped": [
                {"name": step.name, "reason": step.reason}
                for step in self.steps
                if not step.applied
            ],
            "measured": self.measurement.as_dict() if self.measurement else {},
            "limits": {
                "max_noise_reduction_db": MAX_NOISE_REDUCTION_DB,
                "max_compression_ratio": MAX_COMPRESSION_RATIO,
                "max_deesser_intensity": DEESSER_MAX,
            },
        }

    def summary(self) -> str:
        """One line a person can read after a render."""
        if not self.changed:
            return "audio left as recorded; nothing measured above its threshold"
        return "audio cleaned: " + ", ".join(step.reason for step in self.steps if step.applied)


NO_CLEANUP = VoiceCleanup(steps=(), measurement=None)


def plan_cleanup(measurement: VoiceMeasurement | None) -> VoiceCleanup:
    """Decide the chain from the measurement. No measurement, no processing."""
    if measurement is None:
        return NO_CLEANUP
    return VoiceCleanup(
        steps=(
            _rumble_step(measurement),
            _hum_step(measurement),
            _denoise_step(measurement),
            _sibilance_step(measurement),
            _dynamics_step(measurement),
            _clipping_step(measurement),
        ),
        measurement=measurement,
    )


def _rumble_step(m: VoiceMeasurement) -> CleanupStep:
    present = m.low_band_relative_db > RUMBLE_RELATIVE_DB
    return CleanupStep(
        name="rumble",
        applied=present,
        reason=(
            f"high-pass {HIGHPASS_HZ} Hz: energy below 60 Hz is "
            f"{m.low_band_relative_db:.1f} dB under the voice, above the "
            f"{RUMBLE_RELATIVE_DB:.0f} dB threshold"
            if present
            else f"no rumble: energy below 60 Hz is {m.low_band_relative_db:.1f} dB under the voice"
        ),
        filter=f"highpass=f={HIGHPASS_HZ}:poles={HIGHPASS_POLES}" if present else "",
        detail={"low_band_relative_db": round(m.low_band_relative_db, 1)} if present else {},
    )


def _hum_step(m: VoiceMeasurement) -> CleanupStep:
    fundamental = 50 if m.hum_50_relative_db >= m.hum_60_relative_db else 60
    level = max(m.hum_50_relative_db, m.hum_60_relative_db)
    tonal = level >= m.low_band_relative_db + HUM_OVER_RUMBLE_DB
    present = level > HUM_RELATIVE_DB and tonal
    return CleanupStep(
        name="mains hum",
        applied=present,
        reason=(
            f"notch {fundamental} Hz: a narrow band there is {level:.1f} dB under the "
            "voice and concentrated enough to be a tone rather than rumble"
            if present
            else f"no hum: the strongest mains band is {level:.1f} dB under the voice"
        ),
        filter=(
            f"equalizer=f={fundamental}:width_type=h:w={HUM_NOTCH_WIDTH_HZ:.0f}"
            f":g={HUM_NOTCH_GAIN_DB:.0f}"
            if present
            else ""
        ),
        detail={"fundamental_hz": fundamental, "level_db": round(level, 1)} if present else {},
    )


def _denoise_step(m: VoiceMeasurement) -> CleanupStep:
    audible = m.noise_floor_db > NOISE_FLOOR_DB
    noisy = m.snr_db < NOISE_SNR_DB
    present = audible and noisy
    reduction = min(
        MAX_NOISE_REDUCTION_DB, max(MIN_NOISE_REDUCTION_DB, round(NOISE_SNR_DB - m.snr_db))
    )
    floor = min(-20.0, max(-80.0, m.noise_floor_db))
    return CleanupStep(
        name="broadband noise",
        applied=present,
        reason=(
            f"denoise {reduction:.0f} dB: the noise floor is {m.noise_floor_db:.1f} dBFS, "
            f"only {m.snr_db:.1f} dB under speech"
            if present
            else f"no denoising: {m.snr_db:.1f} dB of headroom over a "
            f"{m.noise_floor_db:.1f} dBFS floor"
        ),
        filter=f"afftdn=nr={reduction:.0f}:nf={floor:.0f}:tn=1" if present else "",
        detail=(
            {"noise_reduction_db": reduction, "noise_floor_db": round(floor, 1)} if present else {}
        ),
    )


def _sibilance_step(m: VoiceMeasurement) -> CleanupStep:
    present = m.sibilance_relative_db > SIBILANCE_RELATIVE_DB
    return CleanupStep(
        name="sibilance",
        applied=present,
        reason=(
            f"de-ess at intensity {DEESSER_INTENSITY}: 5-9 kHz sits "
            f"{m.sibilance_relative_db:.1f} dB under the voice, above the "
            f"{SIBILANCE_RELATIVE_DB:.0f} dB threshold"
            if present
            else f"no de-essing: 5-9 kHz sits {m.sibilance_relative_db:.1f} dB under the voice"
        ),
        filter=f"deesser=i={DEESSER_INTENSITY}:m=0.5:f=0.5" if present else "",
        detail={"intensity": DEESSER_INTENSITY} if present else {},
    )


def _dynamics_step(m: VoiceMeasurement) -> CleanupStep:
    lra = m.loudness_range_lu
    present = lra is not None and lra > WIDE_LRA_LU
    return CleanupStep(
        name="dynamics",
        applied=present,
        reason=(
            f"compress {MAX_COMPRESSION_RATIO:g}:1: the loudness range is {lra:.1f} LU, "
            f"above the {WIDE_LRA_LU:.0f} LU threshold"
            if present and lra is not None
            else f"no compression: the loudness range is {lra:.1f} LU"
            if lra is not None
            else "no compression: the loudness range was not measured"
        ),
        filter=(
            f"acompressor=threshold={COMPRESSOR_THRESHOLD_DB:.0f}dB"
            f":ratio={MAX_COMPRESSION_RATIO:g}:attack={COMPRESSOR_ATTACK_MS}"
            f":release={COMPRESSOR_RELEASE_MS}"
            if present
            else ""
        ),
        detail={"ratio": MAX_COMPRESSION_RATIO, "loudness_range_lu": round(lra, 1)}
        if present and lra is not None
        else {},
    )


def _clipping_step(m: VoiceMeasurement) -> CleanupStep:
    """Never applied. Clipping is reported because it cannot be undone."""
    return CleanupStep(
        name="clipping",
        applied=False,
        reason=(
            f"the recording peaks at {m.peak_db:.1f} dBFS and is clipped; that is damage "
            "in the source and this tool will not invent the missing waveform. Re-record "
            "with more headroom if the distortion is audible."
            if m.clipped
            else f"not clipped: peaks at {m.peak_db:.1f} dBFS"
        ),
    )


def measure_voice(
    inputs: list[str],
    speech_graph: str,
    out_label: str,
    *,
    loudness_range_lu: float | None = None,
) -> VoiceMeasurement | None:
    """Measure the edit's speech. Returns None when nothing can be measured.

    ``inputs`` is the ffmpeg input argument list, ``-i`` flags included, the
    same as :func:`social_video.edl.loudness.measure_loudness` takes.
    """
    windows = _window_levels(inputs, speech_graph, out_label)
    if not windows:
        log.debug("voice measurement produced no usable windows; skipping cleanup")
        return None
    speech = _percentile(windows, 90)
    floor = _percentile(windows, 10)
    overall = _overall_stats(inputs, speech_graph, out_label, "")
    if overall is None:
        return None
    full_rms = overall.get("rms")
    if full_rms is None or not math.isfinite(full_rms):
        return None
    bands = {
        "low": "lowpass=f=60:poles=2,lowpass=f=60:poles=2,",
        "hum50": "bandpass=f=50:width_type=h:w=6,",
        "hum60": "bandpass=f=60:width_type=h:w=6,",
        "sibilance": "bandpass=f=7000:width_type=h:w=4000,",
    }
    measured: dict[str, float] = {}
    for name, prefix in bands.items():
        stats = _overall_stats(inputs, speech_graph, out_label, prefix)
        value = (stats or {}).get("rms")
        measured[name] = value - full_rms if value is not None and math.isfinite(value) else -120.0
    return VoiceMeasurement(
        speech_level_db=speech,
        noise_floor_db=floor,
        peak_db=overall.get("peak", -120.0),
        flat_factor=overall.get("flat", 0.0),
        low_band_relative_db=measured["low"],
        hum_50_relative_db=measured["hum50"],
        hum_60_relative_db=measured["hum60"],
        sibilance_relative_db=measured["sibilance"],
        loudness_range_lu=loudness_range_lu,
        windows=len(windows),
    )


def _analysis_head() -> str:
    return f"atrim=duration={MAX_ANALYSIS_SECONDS:.3f},"


def _window_levels(inputs: list[str], speech_graph: str, out_label: str) -> list[float]:
    """Per-window RMS, which is what makes a real noise floor measurable."""
    with tempfile.TemporaryDirectory(prefix="social-video-voice-") as work:
        report = Path(work) / "windows.txt"
        graph = (
            f"{speech_graph};{out_label}{_analysis_head()}"
            f"asetnsamples=n={WINDOW_SAMPLES},"
            "astats=metadata=1:reset=1:measure_perchannel=none,"
            "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level"
            f":file={escape_filter_path(report)}[vm]"
        )
        args = [*inputs, "-filter_complex", graph, "-map", "[vm]", "-f", "null", "-"]
        try:
            run_ffmpeg(args, desc="measure voice windows", timeout=1800)
        except Exception as exc:  # measurement must never break a render
            log.debug("voice window measurement failed: %s", exc)
            return []
        if not report.is_file():
            return []
        values: list[float] = []
        for line in report.read_text(encoding="utf-8", errors="replace").splitlines():
            match = _RMS_LINE.search(line)
            if not match:
                continue
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            if math.isfinite(value):
                values.append(value)
        return values


def _overall_stats(
    inputs: list[str], speech_graph: str, out_label: str, band: str
) -> dict[str, float] | None:
    graph = f"{speech_graph};{out_label}{_analysis_head()}{band}astats=measure_perchannel=none[vs]"
    args = [*inputs, "-filter_complex", graph, "-map", "[vs]", "-f", "null", "-"]
    try:
        # run_ffmpeg returns stderr, which is where astats prints.
        stderr = run_ffmpeg(args, desc="measure voice band", timeout=1800)
    except Exception as exc:  # measurement must never break a render
        log.debug("voice band measurement failed: %s", exc)
        return None
    stats: dict[str, float] = {}
    for line in stderr.splitlines():
        match = _STAT_LINE.match(line.strip())
        if not match:
            continue
        key = match.group("key").strip().casefold()
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        if key == "rms level db":
            stats.setdefault("rms", value)
        elif key == "peak level db":
            stats.setdefault("peak", value)
        elif key == "flat factor":
            stats.setdefault("flat", value)
    return stats or None


def _percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return -120.0
    position = (len(ordered) - 1) * percent / 100.0
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight
