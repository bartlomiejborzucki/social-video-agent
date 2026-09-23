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
from social_video.reframe.detect import FrameFaces, detect_faces
from social_video.reframe.smooth import SmoothingConfig, dedupe_keyframes, smooth_positions
from social_video.schemas.edl import CropKeyframe, Pane, PaneFit, ReframeMode, ReframePlan

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
    audio_source: Path | None = None,
    turns: list[tuple[float, float, str]] | None = None,
) -> ReframePlan:
    """Decide how to fit a range of a source onto a vertical canvas.

    ``turns`` are diarized speaker turns in source seconds. With two or more
    speakers in the range, speaker mode follows whoever holds the floor and
    cuts between them at turn changes, instead of picking one face for the
    whole range.
    """
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

    if mode is ReframeMode.SPLIT_STACK:
        return _plan_split(source, start, end, (src_w, src_h), (out_width, out_height))

    speaker_note = ""
    chosen_track = None
    try:
        if mode is ReframeMode.SPEAKER:
            from social_video.reframe.speaker import analyse_speaker

            samples, tracks, choice = analyse_speaker(
                source, start=start, end=end, audio_source=audio_source
            )
            in_range = [
                (max(a, start), min(b, end), who)
                for a, b, who in turns or []
                if b > start and a < end
            ]
            followed = (
                _follow_turns(samples, tracks, in_range)
                if len({who for _, _, who in in_range}) >= 2
                else None
            )
            if followed is not None:
                samples, turn_cuts, speaker_note = followed
                scene_cuts = sorted([*(scene_cuts or []), *turn_cuts])
            elif choice.confident:
                chosen_track = next((t for t in tracks if t.id == choice.track_id), None)
            # Naming the fallback is the point: a crop that silently follows the
            # wrong person in a two-hander is worse than one that says it guessed.
            if followed is None:
                speaker_note = (
                    f"speaker mode: {choice.reason}; "
                    if choice.confident
                    else f"speaker mode fell back to face prominence: {choice.reason}; "
                )
        else:
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

    if chosen_track is not None:
        chosen: list = []
        for index, sample in enumerate(samples):
            face = chosen_track.faces.get(index)
            chosen.append(sample if face is None else _only(sample, face))
        samples = chosen

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
            speaker_note + f"face-aware crop from {src_w}x{src_h}; faces found in "
            f"{coverage:.0%} of {len(samples)} sampled frames; "
            f"{len(keyframes)} keyframe(s) after smoothing and dead zone"
        ),
    )


#: A person must be found in at least this share of samples to get a pane.
SPLIT_MIN_COVERAGE = 0.3
#: A pane shows this many face-heights of picture, so shoulders and gesture
#: stay in shot rather than a floating head.
SPLIT_FACE_HEIGHTS = 3.0


def split_panes(
    samples: list[FrameFaces], source: tuple[int, int], canvas: tuple[int, int]
) -> list[Pane] | str:
    """Two panes, one per person, left person on top; or why there cannot be.

    Each pane is fixed for the range, centred on where that person's face
    usually is. A two-hander where people move across each other is not a
    stack; it is a reason to cut differently.
    """
    from statistics import median

    from social_video.reframe.speaker import track_faces

    src_w, src_h = source
    out_w, out_h = canvas
    tracks = [
        t for t in track_faces(samples) if t.coverage >= SPLIT_MIN_COVERAGE * max(1, len(samples))
    ]
    if len(tracks) < 2:
        return (
            f"split_stack needs two people in shot; {len(tracks)} found often enough "
            f"(in at least {SPLIT_MIN_COVERAGE:.0%} of {len(samples)} sampled frames)"
        )
    people = sorted(tracks, key=lambda t: -t.coverage)[:2]
    band_aspect = out_w / (out_h / 2)
    panes: list[Pane] = []
    for track in sorted(people, key=lambda t: median(f.center[0] for f in t.faces.values())):
        faces = list(track.faces.values())
        cx = median(f.center[0] for f in faces)
        cy = median(f.center[1] for f in faces)
        face_h = median(f.height for f in faces)
        height = min(src_h, round(face_h * SPLIT_FACE_HEIGHTS))
        width = min(src_w, round(height * band_aspect))
        height = min(height, round(width / band_aspect))
        x = round(_clamp(cx - width / 2, 0, src_w - width))
        y = round(_clamp(cy - height * HEAD_ROOM, 0, src_h - height))
        panes.append(
            Pane(x=x, y=y, width=width, height=height, share=0.5, fit=PaneFit.COVER,
                 label=f"person {len(panes) + 1}")
        )  # fmt: skip
    return panes


def _plan_split(
    source: Path, start: float, end: float, src: tuple[int, int], canvas: tuple[int, int]
) -> ReframePlan:
    try:
        samples = detect_faces(source, start=start, end=end)
    except Exception as exc:  # detection is best-effort; framing must still happen
        samples = []
        log.warning("face detection failed (%s); split_stack cannot place panes", exc)
    panes = split_panes(samples, src, canvas)
    if isinstance(panes, str):
        crop_w, crop_h = crop_size_for(*src, *canvas)
        return ReframePlan(
            mode=ReframeMode.CENTER,
            crop_width=crop_w,
            crop_height=crop_h,
            keyframes=[CropKeyframe(t=0.0, x=(src[0] - crop_w) // 2, y=(src[1] - crop_h) // 2)],
            reason=f"centre crop: {panes}",
        )
    return ReframePlan(
        mode=ReframeMode.SPLIT_STACK,
        panes=panes,
        reason=f"two people stacked, one pane each, from {len(samples)} sampled frames",
    )


def _follow_turns(
    samples: list[FrameFaces], tracks: list, turns: list[tuple[float, float, str]]
) -> tuple[list[FrameFaces], list[float], str] | None:
    """Each sample keeps only the face of whoever holds the floor.

    Returns the filtered samples, the turn changes to treat as cuts -- the
    crop jumps there, as an editor would cut, rather than panning across --
    and the note for the plan; or ``None`` when fewer than two speakers could
    be matched to a face, so the caller keeps single-speaker framing.
    """
    from social_video.reframe.speaker import assign_speakers, speaker_at

    times = [sample.t for sample in samples]
    faces_of = assign_speakers(tracks, times, turns)
    if len(faces_of) < 2:
        return None
    by_id = {track.id: track for track in tracks}
    holders = speaker_at(times, turns)
    kept: list[FrameFaces] = []
    cuts: list[float] = []
    previous: str | None = None
    for index, (sample, holder) in enumerate(zip(samples, holders, strict=True)):
        track = by_id.get(faces_of.get(holder, -1)) if holder else None
        face = track.faces.get(index) if track else None
        kept.append(sample if face is None else _only(sample, face))
        if holder is not None and previous is not None and holder != previous:
            cuts.append(sample.t)
        previous = holder or previous
    names = ", ".join(f"{who}->face {track_id}" for who, track_id in sorted(faces_of.items()))
    return kept, cuts, f"speaker mode follows diarized turns ({names}); "


def _only(sample: FrameFaces, face) -> FrameFaces:
    """Keep just the tracked speaker, so the existing crop logic follows them."""
    return FrameFaces(t=sample.t, faces=(face,))


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
