"""Producing a reframe plan for one range.

The output is data, not a filter string: a crop size plus keyframes, with the
reason recorded. That keeps the framing decision reviewable and editable, which
is the whole point of an inspectable artifact.

Architecture follows ClipsAI (MIT): the crop is piecewise constant across
segments bounded by scene cuts, rather than tracked per frame. Scene changes are
where a crop is *allowed* to jump without looking like a mistake.
"""

from __future__ import annotations

import logging
from pathlib import Path

from social_video.ffmpeg.probe import probe
from social_video.reframe.detect import detect_faces
from social_video.reframe.smooth import SmoothingConfig, dedupe_keyframes, smooth_positions
from social_video.schemas.edl import CropKeyframe, ReframeMode, ReframePlan

log = logging.getLogger(__name__)

#: Faces sit better a little above centre than dead centre.
HEAD_ROOM = 0.42


def crop_size_for(src_w: int, src_h: int, out_w: int, out_h: int) -> tuple[int, int]:
    """Largest crop of the output aspect that fits inside the source."""
    target = out_w / out_h
    if src_w / src_h > target:
        crop_h = src_h
        crop_w = min(src_w, round(src_h * target))
    else:
        crop_w = src_w
        crop_h = min(src_h, round(src_w / target))
    # Even dimensions, because yuv420p subsamples chroma by two.
    return max(2, crop_w - crop_w % 2), max(2, crop_h - crop_h % 2)


def plan_reframe(
    source: Path,
    *,
    start: float,
    end: float,
    out_width: int,
    out_height: int,
    mode: ReframeMode = ReframeMode.FACE,
    scene_cuts: list[float] | None = None,
    smoothing: SmoothingConfig | None = None,
) -> ReframePlan:
    """Decide how to fit a range of a source onto a vertical canvas."""
    info = probe(source)
    if info.video is None:
        return ReframePlan(mode=ReframeMode.FIT, reason="source has no video stream")

    src_w, src_h = info.video.display_size
    crop_w, crop_h = crop_size_for(src_w, src_h, out_width, out_height)

    if crop_w >= src_w and crop_h >= src_h:
        return ReframePlan(
            mode=ReframeMode.FIT,
            reason="source already matches the output aspect; no crop needed",
        )

    if mode is ReframeMode.FIT:
        return ReframePlan(
            mode=ReframeMode.FIT, reason="fit requested; padding instead of cropping"
        )

    centre_x = (src_w - crop_w) // 2
    centre_y = (src_h - crop_h) // 2

    if mode is ReframeMode.CENTER:
        return ReframePlan(
            mode=ReframeMode.CENTER,
            crop_width=crop_w,
            crop_height=crop_h,
            keyframes=[CropKeyframe(t=0.0, x=centre_x, y=centre_y)],
            reason="centre crop",
        )

    if mode is ReframeMode.SPEAKER:
        # Say so rather than quietly doing something else. Choosing the active
        # speaker needs audio-visual speaker detection, which is not built yet;
        # until it is, this picks the most prominent face, which is right for a
        # single subject and a guess for a conversation.
        log.warning(
            "speaker-aware framing is not implemented yet; falling back to "
            "face-prominence framing, which picks the largest face rather than "
            "the one currently talking"
        )

    try:
        samples = detect_faces(source, start=start, end=end)
    except Exception as exc:  # detection is best-effort; framing must still happen
        log.warning("face detection failed (%s); falling back to a centre crop", exc)
        return ReframePlan(
            mode=ReframeMode.CENTER,
            crop_width=crop_w,
            crop_height=crop_h,
            keyframes=[CropKeyframe(t=0.0, x=centre_x, y=centre_y)],
            reason=f"centre crop: face detection unavailable ({exc})",
        )

    hits = [s for s in samples if s.primary is not None]
    if not hits:
        return ReframePlan(
            mode=ReframeMode.CENTER,
            crop_width=crop_w,
            crop_height=crop_h,
            keyframes=[CropKeyframe(t=0.0, x=centre_x, y=centre_y)],
            reason="centre crop: no faces detected in this range",
        )

    times = [s.t - start for s in hits]
    raw_x: list[float] = []
    raw_y: list[float] = []
    for sample in hits:
        face = sample.primary
        assert face is not None
        cx, cy = face.center
        # Clamp on both sides. clipsai clamps only the low edge, which lets the
        # crop window run past the right or bottom of the frame.
        raw_x.append(_clamp(cx - crop_w / 2.0, 0, src_w - crop_w))
        raw_y.append(_clamp(cy - crop_h * HEAD_ROOM, 0, src_h - crop_h))

    cfg = smoothing or SmoothingConfig()
    smooth_x = smooth_positions(raw_x, span=crop_w, config=cfg)
    smooth_y = smooth_positions(raw_y, span=crop_h, config=cfg)

    if scene_cuts:
        # A crop may jump freely at a scene cut: the viewer is already being
        # shown something new, so the movement reads as intentional.
        smooth_x = _reset_at_cuts(times, smooth_x, raw_x, scene_cuts, start)
        smooth_y = _reset_at_cuts(times, smooth_y, raw_y, scene_cuts, start)

    kept_x = dedupe_keyframes(times, smooth_x, span=crop_w, dead_zone=cfg.dead_zone)
    at_times = {round(t, 3) for t, _ in kept_x}
    keyframes = [
        CropKeyframe(
            t=round(t, 3),
            x=round(_clamp(x, 0, src_w - crop_w)),
            y=round(_clamp(y, 0, src_h - crop_h)),
        )
        for t, x, y in zip(times, smooth_x, smooth_y, strict=True)
        if round(t, 3) in at_times
    ]
    if not keyframes:
        keyframes = [CropKeyframe(t=0.0, x=int(smooth_x[0]), y=int(smooth_y[0]))]

    coverage = len(hits) / max(1, len(samples))
    return ReframePlan(
        mode=mode,
        crop_width=crop_w,
        crop_height=crop_h,
        keyframes=keyframes,
        reason=(
            (
                "speaker mode requested, resolved by face prominence; "
                if mode is ReframeMode.SPEAKER
                else ""
            )
            + f"face-aware crop from {src_w}x{src_h}; faces found in "
            f"{coverage:.0%} of {len(samples)} sampled frames; "
            f"{len(keyframes)} keyframe(s) after smoothing and dead zone"
        ),
    )


def _reset_at_cuts(
    times: list[float],
    smoothed: list[float],
    raw: list[float],
    cuts: list[float],
    offset: float,
) -> list[float]:
    """Let the crop snap to the true position immediately after a scene cut."""
    relative = sorted(c - offset for c in cuts)
    out = list(smoothed)
    for cut in relative:
        for index, t in enumerate(times):
            if t >= cut:
                out[index] = raw[index]
                break
    return out


def _clamp(value: float, low: float, high: float) -> float:
    if high < low:
        return low
    return max(low, min(value, high))
