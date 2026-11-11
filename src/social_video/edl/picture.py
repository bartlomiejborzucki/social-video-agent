"""Measured picture correction: what each recording needs, and no more.

The picture gets the treatment the voice already has (`edl/voice.py`). A
recording is measured where the edit shows it, and each correction is applied
only when its own threshold is crossed, scaled to the measurement and stopped
at a ceiling:

* a dark recording is lifted, toward the level of the better-exposed
  recordings in the same edit when there are any;
* a flat one, or one flattened by that lift, gets its contrast back;
* a recording the edit enlarges is sharpened, by how much it is enlarged;
* one compressed harder than a floor is lightly denoised before any of it.

A good recording is left exactly as recorded. A colour cast is reported and
never corrected: a room with green walls measures as a cast, and guessing the
light a scene was shot in is invention. Nothing here can recover detail a
small or heavily compressed file does not hold, which is why such a source is
also named as one (`weak_source_notes`) so the original can be asked for.

Every decision is recorded with the measurement behind it and the ceilings in
force, per source, so brand QA checks what was done rather than what was
intended.
"""

from __future__ import annotations

import functools
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

from social_video.errors import FFmpegError
from social_video.ffmpeg.filters import TONEMAP_CHAIN
from social_video.ffmpeg.probe import MediaInfo
from social_video.ffmpeg.run import has_filter, has_libzimg, run_ffmpeg_bytes
from social_video.schemas.edl import EDL, EDLRange, ReframeMode

log = logging.getLogger(__name__)

# -- how it is measured -------------------------------------------------------

#: Frames read per recording, spread over the parts of it the edit uses.
SAMPLES_PER_SOURCE = 10
#: Width the sampled frames are reduced to. Brightness needs no more.
MEASURE_WIDTH = 160
#: The share of the shown picture, from its top, that is measured. In a
#: talking head the speaker is there; below it are hands, a table, captions.
MEASURED_SHARE = 0.66

# -- thresholds and ceilings --------------------------------------------------
# Luma is 0-255. Set so that a phone recording made indoors by lamp light is
# lifted and one made by a window in daylight is left alone.

#: Median brightness under which the speaker reads as underexposed.
DARK_MEDIAN = 105.0
#: Where a lift aims when no other recording in the edit sets the level.
TARGET_MEDIAN = 120.0
#: A lift never aims higher than this, however bright the other recordings.
TARGET_CEILING = 140.0
#: The strongest lift. Past it the noise in the shadows comes up with them.
MAX_GAMMA = 1.35
#: A lift under this is not worth touching the picture for.
MIN_GAMMA = 1.04
#: Spread between the 5th and 95th percentile under which a picture is flat.
FLAT_SPREAD = 105.0
#: The strongest contrast. A lift flattens the picture; this gives it back.
MAX_CONTRAST = 1.10
#: Contrast restored per unit of gamma applied.
CONTRAST_PER_GAMMA = 0.2
#: How much the edit must enlarge a recording before it is sharpened.
ENLARGED_FROM = 1.15
#: The strongest sharpening (unsharp's luma amount). More draws halos.
MAX_SHARPEN = 0.8
#: Bits per pixel per frame under which compression noise is visible.
LOW_BITS_PER_PIXEL = 0.05
#: Strength of the one denoise applied (hqdn3d luma spatial); never scaled up.
DENOISE_STRENGTH = 1.5
#: Channel imbalance in near-neutral pixels above which a cast is reported.
CAST_REPORTED_FROM = 0.08

#: Enlargement from which a recording is named as a weak source.
WEAK_ENLARGEMENT = 1.5


@dataclass(frozen=True)
class PictureMeasurement:
    """What one recording measures where the edit shows it."""

    median: float
    low: float
    high: float
    #: (R - B) / mean over near-neutral pixels: above zero is warm.
    cast: float
    enlargement: float
    bits_per_pixel: float | None
    frames: int

    @property
    def spread(self) -> float:
        return self.high - self.low

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "median_luma": round(self.median, 1),
            "low_luma": round(self.low, 1),
            "high_luma": round(self.high, 1),
            "spread": round(self.spread, 1),
            "colour_cast": round(self.cast, 3),
            "enlargement": round(self.enlargement, 2),
            "bits_per_pixel": (
                None if self.bits_per_pixel is None else round(self.bits_per_pixel, 3)
            ),
            "frames_measured": self.frames,
        }


@dataclass(frozen=True)
class CorrectionStep:
    """One decision, with the measurement that drove it either way."""

    name: str
    applied: bool
    reason: str
    detail: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceCorrection:
    """What one recording gets: filters before the reframe, and after its scale."""

    steps: tuple[CorrectionStep, ...]
    measurement: PictureMeasurement | None
    #: Runs on the recording's own pixels, before it is cropped and scaled.
    pre: str = ""
    #: Runs after the scale to the canvas and before any padding.
    post_scale: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.pre or self.post_scale)

    def evidence(self) -> dict[str, object]:
        return {
            "changed": self.changed,
            "filters": ",".join(part for part in (self.pre, self.post_scale) if part),
            "applied": [
                {"name": step.name, "reason": step.reason, **step.detail}
                for step in self.steps
                if step.applied
            ],
            "skipped": [
                {"name": step.name, "reason": step.reason}
                for step in self.steps
                if not step.applied
            ],
            "measured": self.measurement.as_dict() if self.measurement else {},
        }


UNTOUCHED = SourceCorrection(steps=(), measurement=None)


@dataclass(frozen=True)
class PictureCorrection:
    """The corrections of one render, by source id."""

    sources: dict[str, SourceCorrection] = field(default_factory=dict)

    def of(self, source_id: str) -> SourceCorrection:
        return self.sources.get(source_id, UNTOUCHED)

    @property
    def changed(self) -> bool:
        return any(item.changed for item in self.sources.values())

    def evidence(self) -> dict[str, object]:
        """What the render manifest records, so QA checks facts not intent."""
        return {
            "changed": self.changed,
            "sources": {name: item.evidence() for name, item in sorted(self.sources.items())},
            "limits": {
                "max_gamma": MAX_GAMMA,
                "max_contrast": MAX_CONTRAST,
                "max_sharpen": MAX_SHARPEN,
                "max_denoise": DENOISE_STRENGTH,
            },
        }

    def summary(self) -> str:
        """One line a person can read after a render."""
        if not self.changed:
            return "picture left as recorded; nothing measured above its threshold"
        parts = [
            f"{name}: " + ", ".join(step.reason for step in item.steps if step.applied)
            for name, item in sorted(self.sources.items())
            if item.changed
        ]
        return "picture corrected: " + "; ".join(parts)


NO_CORRECTION = PictureCorrection()


# -- deciding -----------------------------------------------------------------


def plan_correction(
    measurements: dict[str, PictureMeasurement],
    *,
    unavailable: frozenset[str] = frozenset(),
) -> PictureCorrection:
    """Decide each recording's correction from the measurements of them all.

    ``unavailable`` names ffmpeg filters this build lacks; a step that needs
    one is recorded as skipped instead of silently dropped.
    """
    level = _edit_level(measurements)
    return PictureCorrection(
        {
            name: _plan_source(measurement, level, unavailable)
            for name, measurement in measurements.items()
        }
    )


def _edit_level(measurements: dict[str, PictureMeasurement]) -> float:
    """The brightness a dark recording is lifted toward.

    The level of the recordings that need no lift, so two speakers end closer
    together, bounded so one bright window does not set it.
    """
    exposed = sorted(m.median for m in measurements.values() if m.median >= DARK_MEDIAN)
    if not exposed:
        return TARGET_MEDIAN
    middle = exposed[len(exposed) // 2]
    return min(TARGET_CEILING, max(TARGET_MEDIAN, middle))


def _plan_source(
    m: PictureMeasurement, level: float, unavailable: frozenset[str]
) -> SourceCorrection:
    denoise = _denoise_step(m, unavailable)
    exposure, gamma = _exposure_step(m, level, unavailable)
    contrast, amount = _contrast_step(m, gamma, unavailable)
    sharpen, strength = _sharpen_step(m, unavailable)
    pre: list[str] = []
    if denoise.applied:
        pre.append(f"hqdn3d={DENOISE_STRENGTH}:{DENOISE_STRENGTH}:4:4")
    if exposure.applied or contrast.applied:
        settings = []
        if exposure.applied:
            settings.append(f"gamma={gamma:.3f}")
        if contrast.applied:
            settings.append(f"contrast={amount:.3f}")
        pre.append("eq=" + ":".join(settings))
    return SourceCorrection(
        steps=(denoise, exposure, contrast, sharpen, _cast_step(m)),
        measurement=m,
        pre=",".join(pre),
        post_scale=f"unsharp=5:5:{strength:.2f}:5:5:0.0" if sharpen.applied else "",
    )


def _exposure_step(
    m: PictureMeasurement, level: float, unavailable: frozenset[str]
) -> tuple[CorrectionStep, float]:
    if m.median >= DARK_MEDIAN:
        return CorrectionStep("exposure", False, f"well exposed (median {m.median:.0f})"), 1.0
    # eq's gamma maps a level v (0-1) to v ** (1 / gamma).
    wanted = math.log(max(m.median, 1.0) / 255.0) / math.log(level / 255.0)
    gamma = min(MAX_GAMMA, wanted)
    if gamma < MIN_GAMMA:
        return CorrectionStep("exposure", False, f"close to the level (median {m.median:.0f})"), 1.0
    if "eq" in unavailable:
        return CorrectionStep("exposure", False, "dark, but this ffmpeg has no eq filter"), 1.0
    reached = 255.0 * (m.median / 255.0) ** (1.0 / gamma)
    capped = " (at the ceiling)" if gamma >= MAX_GAMMA else ""
    return (
        CorrectionStep(
            "exposure",
            True,
            f"dark picture lifted from {m.median:.0f} to about {reached:.0f}{capped}",
            {"gamma": round(gamma, 3), "target_luma": round(level, 1)},
        ),
        gamma,
    )


def _contrast_step(
    m: PictureMeasurement, gamma: float, unavailable: frozenset[str]
) -> tuple[CorrectionStep, float]:
    amount = 1.0 + CONTRAST_PER_GAMMA * (gamma - 1.0)
    reason = "contrast restored after the lift"
    if m.spread < FLAT_SPREAD:
        amount = max(amount, FLAT_SPREAD / max(m.spread, 1.0))
        reason = f"flat picture (spread {m.spread:.0f})"
    amount = min(MAX_CONTRAST, amount)
    if amount < 1.02:
        return CorrectionStep("contrast", False, f"enough contrast (spread {m.spread:.0f})"), 1.0
    if "eq" in unavailable:
        return CorrectionStep("contrast", False, "flat, but this ffmpeg has no eq filter"), 1.0
    return CorrectionStep("contrast", True, reason, {"contrast": round(amount, 3)}), amount


def _sharpen_step(
    m: PictureMeasurement, unavailable: frozenset[str]
) -> tuple[CorrectionStep, float]:
    if m.enlargement < ENLARGED_FROM:
        return (
            CorrectionStep("sharpen", False, f"not enlarged ({m.enlargement:.2f}x)"),
            0.0,
        )
    if "unsharp" in unavailable:
        return CorrectionStep("sharpen", False, "enlarged, but this ffmpeg has no unsharp"), 0.0
    strength = min(MAX_SHARPEN, 0.25 + 0.4 * (m.enlargement - 1.0))
    return (
        CorrectionStep(
            "sharpen",
            True,
            f"enlarged {m.enlargement:.1f}x, sharpened",
            {"sharpen": round(strength, 2)},
        ),
        strength,
    )


def _denoise_step(m: PictureMeasurement, unavailable: frozenset[str]) -> CorrectionStep:
    if m.bits_per_pixel is None or m.bits_per_pixel >= LOW_BITS_PER_PIXEL:
        return CorrectionStep("denoise", False, "not heavily compressed")
    if "hqdn3d" in unavailable:
        return CorrectionStep("denoise", False, "compressed, but this ffmpeg has no hqdn3d")
    return CorrectionStep(
        "denoise",
        True,
        f"heavily compressed ({m.bits_per_pixel:.3f} bits per pixel), lightly denoised",
        {"denoise": DENOISE_STRENGTH},
    )


def _cast_step(m: PictureMeasurement) -> CorrectionStep:
    """Reported, never corrected: a coloured room measures the same as a cast."""
    if abs(m.cast) < CAST_REPORTED_FROM:
        return CorrectionStep("colour cast", False, "neutral")
    tone = "warm" if m.cast > 0 else "cool"
    return CorrectionStep(
        "colour cast",
        False,
        f"reads {tone} ({m.cast:+.2f}); not corrected, the room may simply be that colour",
    )


# -- measuring ----------------------------------------------------------------


def shown_region(
    rng: EDLRange, info: MediaInfo, canvas: tuple[int, int], default: ReframeMode
) -> tuple[int, int, int, int]:
    """The part of the recording a range shows: width, height, x, y.

    The same geometry `_reframe_filter` renders, without its animation: where
    the crop moves, its first position stands for the range.
    """
    out_w, out_h = canvas
    src_w, src_h = info.video.display_size if info.video else (out_w, out_h)
    plan = rng.reframe
    mode = plan.mode if plan else default
    width, height, x, y = src_w, src_h, 0, 0
    if mode is ReframeMode.SPLIT_STACK:
        pass  # several regions; the whole frame stands for them
    elif mode is not ReframeMode.FIT and plan and plan.crop_width and plan.crop_height:
        width, height = min(plan.crop_width, src_w), min(plan.crop_height, src_h)
        if plan.keyframes:
            x = int(min(max(plan.keyframes[0].x, 0), src_w - width))
            y = int(min(max(plan.keyframes[0].y, 0), src_h - height))
        else:
            x, y = (src_w - width) // 2, (src_h - height) // 2
    elif mode is not ReframeMode.FIT:
        target = out_w / out_h
        if src_w / src_h > target:
            width = max(2, round(src_h * target / 2) * 2)
            x = (src_w - width) // 2
        else:
            height = max(2, round(src_w / target / 2) * 2)
            y = (src_h - height) // 2
    if rng.zoom > 1.0:
        # The same push-in the render makes: on the measured eyes, else the centre.
        focus_x = plan.focus_x if plan and plan.focus_x is not None else 0.5
        focus_y = plan.focus_y if plan and plan.focus_y is not None else 0.5
        zoomed_w, zoomed_h = int(width / rng.zoom), int(height / rng.zoom)
        x, y = x + int((width - zoomed_w) * focus_x), y + int((height - zoomed_h) * focus_y)
        width, height = zoomed_w, zoomed_h
    return max(2, width), max(2, height), x, y


def enlargement(region: tuple[int, int, int, int], canvas: tuple[int, int]) -> float:
    """How many times a shown region is scaled up to fit the canvas."""
    width, height, _x, _y = region
    return min(canvas[0] / width, canvas[1] / height)


def bits_per_pixel(info: MediaInfo) -> float | None:
    """The video's bits per pixel per frame; ``None`` when it cannot be known."""
    video = info.video
    if video is None or not video.width or not video.height:
        return None
    rate = video.bit_rate
    if rate is None and info.duration > 0:
        rate = int(info.size_bytes * 8 / info.duration)  # the whole file: an upper bound
    if not rate:
        return None
    return rate / (video.width * video.height * max(video.fps_float, 1.0))


def measure_sources(
    edl: EDL, infos: list[MediaInfo], *, default: ReframeMode | None = None
) -> dict[str, PictureMeasurement]:
    """Measure every recording the edit shows, where it shows it.

    A recording that cannot be measured is left out; the caller decides
    whether that is acceptable.
    """
    final = (edl.output_width, edl.output_height)
    reframe = default or edl.default_reframe
    by_source: dict[str, list[tuple[EDLRange, MediaInfo]]] = {}
    for rng, info in zip(edl.ranges, infos, strict=True):
        by_source.setdefault(rng.effective_video_source, []).append((rng, info))
    measured: dict[str, PictureMeasurement] = {}
    for name, uses in by_source.items():
        info = uses[0][1]
        if info.video is None:
            continue
        total = sum(max(r.visual_content_end - r.effective_video_start, 0.0) for r, _ in uses)
        if total <= 0:
            continue
        # The longest use of the recording stands for where it is shown.
        longest = max(
            uses, key=lambda use: use[0].visual_content_end - use[0].effective_video_start
        )
        region = shown_region(longest[0], info, final, reframe)
        scale = _weighted_enlargement(uses, final, reframe)
        times = _sample_times([(r.effective_video_start, r.visual_content_end) for r, _ in uses])
        try:
            levels = _levels(
                str(info.path), info.path.stat().st_mtime_ns, region, times, info.video.is_hdr
            )
        except (FFmpegError, OSError, ValueError) as exc:  # measurement must never break a render
            log.info("picture of %s could not be measured: %s", name, exc)
            continue
        if levels is None:
            continue
        median, low, high, cast, frames = levels
        measured[name] = PictureMeasurement(
            median=median,
            low=low,
            high=high,
            cast=cast,
            enlargement=scale,
            bits_per_pixel=bits_per_pixel(info),
            frames=frames,
        )
    return measured


def _weighted_enlargement(
    uses: list[tuple[EDLRange, MediaInfo]], canvas: tuple[int, int], reframe: ReframeMode
) -> float:
    """How much the edit enlarges a recording, weighted by how long each use lasts."""
    total = sum(max(r.visual_content_end - r.effective_video_start, 0.0) for r, _ in uses)
    if total <= 0:
        return 1.0
    return (
        sum(
            enlargement(shown_region(r, i, canvas, reframe), canvas)
            * max(r.visual_content_end - r.effective_video_start, 0.0)
            for r, i in uses
        )
        / total
    )


def _sample_times(spans: list[tuple[float, float]]) -> tuple[float, ...]:
    """Moments spread evenly over the spans, in proportion to their length."""
    total = sum(max(end - start, 0.0) for start, end in spans)
    if total <= 0:
        return ()
    count = max(1, min(SAMPLES_PER_SOURCE, int(total / 0.5) or 1))
    times = []
    for index in range(count):
        offset = total * (index + 0.5) / count
        for start, end in spans:
            length = max(end - start, 0.0)
            if offset <= length:
                times.append(round(start + offset, 3))
                break
            offset -= length
    return tuple(times)


@functools.lru_cache(maxsize=64)
def _levels(
    path: str,
    _mtime_ns: int,
    region: tuple[int, int, int, int],
    times: tuple[float, ...],
    hdr: bool,
) -> tuple[float, float, float, float, int] | None:
    """Median, 5th and 95th percentile luma, the cast, and the frames read.

    Cached for the process: a delivery renders one edit several times.
    """
    import numpy as np

    width, height, x, y = region
    measured_h = max(2, int(height * MEASURED_SHARE) // 2 * 2)
    out_h = max(2, round(MEASURE_WIDTH * measured_h / width / 2) * 2)
    chain = [f"crop={width}:{measured_h}:{x}:{y}", f"scale={MEASURE_WIDTH}:{out_h}:flags=area"]
    if hdr and has_libzimg():
        chain.insert(0, TONEMAP_CHAIN)  # measure what is rendered, not PQ code values
    frames = []
    for at in times:
        raw = run_ffmpeg_bytes(
            ["-v", "error", "-ss", f"{at:.3f}", "-i", path, "-frames:v", "1",
             "-vf", ",".join(chain), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            desc=f"measure the picture of {Path(path).name}",
            timeout=120,
        )  # fmt: skip
        if len(raw) == MEASURE_WIDTH * out_h * 3:
            frames.append(np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.float64))
    if not frames:
        return None
    pixels = np.concatenate(frames)
    red, green, blue = pixels[:, 0], pixels[:, 1], pixels[:, 2]
    luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    low, median, high = (float(v) for v in np.percentile(luma, [5, 50, 95]))
    # Near-neutral midtones: where a cast shows and a coloured object does not.
    spread = pixels.max(axis=1) - pixels.min(axis=1)
    neutral = (spread < 28) & (luma > 60) & (luma < 200)
    cast = 0.0
    if int(neutral.sum()) > 200:
        mean = float(pixels[neutral].mean())
        cast = float((red[neutral].mean() - blue[neutral].mean()) / max(mean, 1.0))
    return median, low, high, cast, len(frames)


def unavailable_filters() -> frozenset[str]:
    """The filters a correction may use that this ffmpeg does not have."""
    return frozenset(name for name in ("eq", "unsharp", "hqdn3d") if not has_filter(name))


# -- naming a weak source -----------------------------------------------------


def weak_source_notes(info: MediaInfo, canvas: tuple[int, int] = (1080, 1920)) -> list[str]:
    """What to say about a recording that cannot fill the output well.

    Before an edit exists the crop is unknown, so this is the least it will be
    enlarged: scaled to cover the canvas. Advice, never a refusal.
    """
    video = info.video
    if video is None:
        return []
    width, height = video.display_size
    if not width or not height:
        return []
    notes = []
    cover = max(canvas[0] / width, canvas[1] / height)
    if cover >= WEAK_ENLARGEMENT:
        notes.append(
            f"{width}x{height} will be enlarged at least {cover:.1f}x to fill "
            f"{canvas[0]}x{canvas[1]}, and no filter restores the detail: ask for the "
            "original file rather than one sent through a messenger"
        )
    density = bits_per_pixel(info)
    if density is not None and density < LOW_BITS_PER_PIXEL:
        notes.append(
            f"heavily compressed ({density:.3f} bits per pixel; a phone records about "
            "0.15): expect soft detail and blocks in the shadows, and ask for the "
            "original file"
        )
    return notes


def edit_source_notes(edl: EDL, infos: list[MediaInfo]) -> dict[str, list[str]]:
    """The same, for an edit that exists: by how much each recording is really enlarged.

    Returns only the recordings there is something to say about.
    """
    final = (edl.output_width, edl.output_height)
    by_source: dict[str, list[tuple[EDLRange, MediaInfo]]] = {}
    for rng, info in zip(edl.ranges, infos, strict=True):
        if info.video is not None:
            by_source.setdefault(rng.effective_video_source, []).append((rng, info))
    found: dict[str, list[str]] = {}
    for name, uses in by_source.items():
        notes = []
        scale = _weighted_enlargement(uses, final, edl.default_reframe)
        if scale >= WEAK_ENLARGEMENT:
            notes.append(
                f"enlarged {scale:.1f}x in this edit, and no filter restores the detail: "
                "ask for the original file rather than one sent through a messenger"
            )
        density = bits_per_pixel(uses[0][1])
        if density is not None and density < LOW_BITS_PER_PIXEL:
            notes.append(
                f"heavily compressed ({density:.3f} bits per pixel; a phone records about "
                "0.15): ask for the original file"
            )
        if notes:
            found[name] = notes
    return found
