"""Rendering an EDL to a finished video.

Architecture note. Upstream encodes every segment to its own file, concatenates
them with ``-c copy``, and then re-encodes the whole timeline again the moment
there are captions or overlays -- which is the normal case. So the stream-copy
optimisation it is built around is spent immediately, and the audio is encoded
twice (segment AAC, then loudnorm AAC) for no benefit.

Here each range is a separate *input* with its own fast seek, and one
``filter_complex`` trims, reframes, fades, concatenates, captions, and
normalises in a single pass. One decode, one encode, no intermediate files, and
because every range is scaled onto the same canvas before the concat filter,
mixing portrait and landscape sources works -- upstream's stream-copy concat
produces an undecodable file in that case.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from social_video.edl.loudness import loudnorm_filter, measure_loudness
from social_video.edl.timeline import Timeline
from social_video.edl.validate import validate_edl
from social_video.ffmpeg.filters import (
    LOUDNORM_I,
    TONEMAP_CHAIN,
    audio_cut_fades,
    crop_position_expression,
    escape_filter_path,
)
from social_video.ffmpeg.probe import (
    MediaInfo,
    frame_aligned_duration,
    probe,
    resolve_output_fps,
)
from social_video.ffmpeg.run import has_libass, has_libzimg, run_ffmpeg
from social_video.schemas.edl import EDL, EDLRange, ReframeMode
from social_video.schemas.qa import RenderManifest
from social_video.schemas.source import SourceManifest

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Quality:
    """An encode preset. Named so intent is visible at the call site."""

    name: str
    crf: int
    preset: str
    #: Longest edge of the output canvas, or None to use the EDL's canvas.
    max_edge: int | None = None
    #: Two-pass loudness is accurate but doubles the audio work.
    two_pass_loudness: bool = False


DRAFT = Quality("draft", crf=30, preset="ultrafast", max_edge=854)
PREVIEW = Quality("preview", crf=24, preset="veryfast", max_edge=1280)
FINAL = Quality("final", crf=19, preset="medium", two_pass_loudness=True)

QUALITIES = {q.name: q for q in (DRAFT, PREVIEW, FINAL)}


def _canvas_for(edl: EDL, quality: Quality) -> tuple[int, int]:
    """Output canvas, scaled down for the cheaper qualities.

    The aspect ratio never changes with quality: a preview that reframes
    differently from the final render is worse than useless.
    """
    width, height = edl.output_width, edl.output_height
    if quality.max_edge and max(width, height) > quality.max_edge:
        scale = quality.max_edge / max(width, height)
        width = max(2, round(width * scale / 2) * 2)
        height = max(2, round(height * scale / 2) * 2)
    return width, height


def _reframe_filter(
    rng: EDLRange, info: MediaInfo, canvas: tuple[int, int], default: ReframeMode
) -> str:
    """Geometry for one range: crop if asked, then fit onto the canvas."""
    out_w, out_h = canvas
    plan = rng.reframe
    mode = plan.mode if plan else default

    src_w, src_h = info.video.display_size if info.video else (out_w, out_h)
    parts: list[str] = []

    if mode is not ReframeMode.FIT and plan and plan.crop_width and plan.crop_height:
        crop_w = min(plan.crop_width, src_w)
        crop_h = min(plan.crop_height, src_h)
        max_x, max_y = src_w - crop_w, src_h - crop_h
        if plan.keyframes:
            # Animate between keyframes. Clamping happens inside the expression
            # builder, on both edges: clipsai clamps only the low side, so its
            # crop can run past the right or bottom of the frame.
            x_expr = crop_position_expression([(k.t, k.x) for k in plan.keyframes], lo=0, hi=max_x)
            y_expr = crop_position_expression([(k.t, k.y) for k in plan.keyframes], lo=0, hi=max_y)
        else:
            x_expr, y_expr = str(max_x // 2), str(max_y // 2)
        parts.append(f"crop={crop_w}:{crop_h}:x='{x_expr}':y='{y_expr}'")
    elif mode is not ReframeMode.FIT:
        # Asked to crop but given no geometry: centre-crop to the output aspect.
        target = out_w / out_h
        if src_w / src_h > target:
            crop_w = max(2, round(src_h * target / 2) * 2)
            parts.append(f"crop={crop_w}:{src_h}:(iw-{crop_w})/2:0")
        else:
            crop_h = max(2, round(src_w / target / 2) * 2)
            parts.append(f"crop={src_w}:{crop_h}:0:(ih-{crop_h})/2")

    if rng.zoom > 1.0:
        # A punch-in is a centred crop by 1/zoom, applied before the final scale
        # so it costs no resolution beyond the zoom itself.
        z = rng.zoom
        parts.append(f"crop=iw/{z:.4f}:ih/{z:.4f}:(iw-iw/{z:.4f})/2:(ih-ih/{z:.4f})/2")

    parts.append(f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos")
    parts.append(f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black")
    parts.append("setsar=1")
    return ",".join(parts)


def build_audio_graph(edl: EDL, infos: list[MediaInfo]) -> tuple[str, str]:
    """Build only the audio half of the graph, for the measurement pass.

    Identical to what the render will do to the audio, so the measurement
    describes the audio that will actually be produced.
    """
    parts: list[str] = []
    labels: list[str] = []
    for index, (rng, info) in enumerate(zip(edl.ranges, infos, strict=True)):
        parts.append(_audio_chain(index, rng, info))
        labels.append(f"[a{index}]")
    parts.append(f"{''.join(labels)}concat=n={len(edl.ranges)}:v=0:a=1[ca]")
    return ";".join(parts), "[ca]"


def _audio_chain(index: int, rng: EDLRange, info: MediaInfo) -> str:
    """The per-range audio chain, shared by the measurement and render passes."""
    if not info.has_audio:
        # A silent range still needs an audio stream or concat refuses. The
        # explicit duration and aformat matter: without them the generated
        # stream can reach the encoder with an unexpected sample format.
        return (
            f"anullsrc=r=48000:cl=stereo:d={rng.output_duration:.4f},"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"asetpts=PTS-STARTPTS[a{index}]"
        )
    # Render the same track that was transcribed. Mapping 0:a:0 unconditionally
    # is what makes a multi-track recording come out silent: OBS puts desktop
    # audio on track 0 and the microphone on track 1.
    track = min(rng.audio_track, max(0, len(info.audio) - 1))
    chain: list[str] = ["aresample=48000:async=1"]
    if rng.speed != 1.0:
        chain.extend(_atempo_chain(rng.speed))
    if rng.audio_gain_db:
        chain.append(f"volume={rng.audio_gain_db:.2f}dB")
    # Short fades at both edges prevent the click that a hard splice makes.
    chain.append(audio_cut_fades(rng.output_duration))
    chain.append("asetpts=PTS-STARTPTS")
    return f"[{index}:a:{track}]{','.join(chain)}[a{index}]"


def build_filtergraph(
    edl: EDL,
    infos: list[MediaInfo],
    *,
    canvas: tuple[int, int],
    fps: str,
    caption_file: Path | None,
    loudnorm: str | None,
) -> tuple[str, str, str]:
    """Build the whole filter graph. Returns (graph, video_label, audio_label)."""
    video_labels: list[str] = []
    audio_labels: list[str] = []
    parts: list[str] = []

    for index, (rng, info) in enumerate(zip(edl.ranges, infos, strict=True)):
        vin = f"{index}:v:0"

        vchain: list[str] = []
        if info.video and info.video.is_hdr and has_libzimg():
            vchain.append(TONEMAP_CHAIN)
        vchain.append(_reframe_filter(rng, info, canvas, edl.default_reframe))
        if rng.speed != 1.0:
            vchain.append(f"setpts=PTS/{rng.speed:.6f}")
        vchain.append(f"fps={fps}")
        # Rebase timestamps so the concat filter joins ranges seamlessly.
        vchain.append("setpts=PTS-STARTPTS")
        parts.append(f"[{vin}]{','.join(vchain)}[v{index}]")
        video_labels.append(f"[v{index}]")

        parts.append(_audio_chain(index, rng, info))
        audio_labels.append(f"[a{index}]")

    pairs = "".join(v + a for v, a in zip(video_labels, audio_labels, strict=True))
    parts.append(f"{pairs}concat=n={len(edl.ranges)}:v=1:a=1[cv][ca]")

    vlabel, alabel = "[cv]", "[ca]"

    for number, overlay in enumerate(edl.overlays):
        src = f"{len(edl.ranges) + number}:v:0"
        prepared = f"[ov{number}]"
        chain = []
        if overlay.scale_width:
            chain.append(f"scale={overlay.scale_width}:-2")
        if overlay.opacity < 1.0:
            chain.append(f"format=yuva420p,colorchannelmixer=aa={overlay.opacity:.3f}")
        chain.append(f"setpts=PTS-STARTPTS+{overlay.start_in_output:.4f}/TB")
        parts.append(f"[{src}]{','.join(chain)}{prepared}")
        out = f"[vo{number}]"
        parts.append(
            f"{vlabel}{prepared}overlay={overlay.x}:{overlay.y}:"
            f"enable='between(t,{overlay.start_in_output:.4f},{overlay.end_in_output:.4f})'"
            f":eof_action=pass:repeatlast=0{out}"
        )
        vlabel = out

    # Captions are burned last, so nothing can be composited over them.
    if caption_file is not None:
        parts.append(f"{vlabel}subtitles={escape_filter_path(caption_file)}[vs]")
        vlabel = "[vs]"

    if loudnorm:
        parts.append(f"{alabel}{loudnorm}[an]")
        alabel = "[an]"

    return ";".join(parts), vlabel, alabel


def _atempo_chain(speed: float) -> list[str]:
    """``atempo`` only accepts 0.5-2.0, so larger changes are chained."""
    chain: list[str] = []
    remaining = speed
    while remaining > 2.0:
        chain.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        chain.append("atempo=0.5")
        remaining /= 0.5
    if abs(remaining - 1.0) > 1e-6:
        chain.append(f"atempo={remaining:.6f}")
    return chain


def render_edl(
    edl: EDL,
    manifest: SourceManifest,
    output: Path,
    *,
    quality: Quality = FINAL,
    caption_file: Path | None = None,
) -> RenderManifest:
    """Render an EDL to a file. Returns a manifest describing what was made."""
    warnings = validate_edl(edl, manifest)
    for warning in warnings:
        log.warning("edl: %s", warning)

    infos = [probe(manifest.by_id(r.source).resolved_path()) for r in edl.ranges]
    canvas = _canvas_for(edl, quality)
    fps = resolve_output_fps(infos, edl.output_fps)
    source_fps = resolve_output_fps(infos, None)

    if caption_file is not None and not has_libass():
        log.warning(
            "this ffmpeg has no libass, so captions cannot be burned in; rendering without them"
        )
        caption_file = None

    measured = None

    inputs: list[str] = []
    for rng, info in zip(edl.ranges, infos, strict=True):
        # Fast seek before -i, duration after: seeks by keyframe then decodes to
        # the exact frame, which is both quick and accurate.
        #
        # The duration is aligned to a whole frame. ffmpeg rounds `-t` up to the
        # next frame, so without this every cut adds up to one frame and the
        # output drifts further from the EDL the more cuts it has.
        inputs += [
            "-ss",
            f"{rng.start:.4f}",
            "-t",
            f"{frame_aligned_duration(rng.duration, fps):.6f}",
            "-i",
            str(info.path),
        ]
    for overlay in edl.overlays:
        inputs += ["-i", str(overlay.file)]

    loudnorm = None
    if edl.normalize_audio:
        # Measure before normalising. loudnorm emits NaN on digitally silent
        # input and the encoder then fails, which would kill any edit whose
        # selected material happens to be quiet. The measurement decodes audio
        # only, so it costs a fraction of the render it informs -- and it lets
        # loudnorm run in its accurate linear mode rather than guessing.
        audio_graph, audio_label = build_audio_graph(edl, infos)
        if quality.two_pass_loudness:
            measured = measure_loudness(inputs, audio_graph, audio_label)
        else:
            measured = _quick_silence_check(inputs, audio_graph, audio_label)
        loudnorm = loudnorm_filter(measured)
        if loudnorm is None:
            log.info("selected audio is silent; skipping loudness normalisation")

    graph, vlabel, alabel = build_filtergraph(
        edl, infos, canvas=canvas, fps=fps, caption_file=caption_file, loudnorm=loudnorm
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-y",
        *inputs,
        "-filter_complex",
        graph,
        "-map",
        vlabel,
        "-map",
        alabel,
        "-c:v",
        "libx264",
        "-preset",
        quality.preset,
        "-crf",
        str(quality.crf),
        "-pix_fmt",
        "yuv420p",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(output),
    ]
    log.info(
        "rendering %s: %d range(s), %dx%d @ %s, quality=%s",
        output.name,
        len(edl.ranges),
        canvas[0],
        canvas[1],
        fps,
        quality.name,
    )
    run_ffmpeg(args, desc=f"render {output.name}", timeout=14400)

    rendered = probe(output)
    return RenderManifest(
        output=str(output),
        edl=edl.name,
        rendered_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        duration=rendered.duration,
        width=canvas[0],
        height=canvas[1],
        frame_rate=fps,
        frame_rate_converted_from=None if fps == source_fps else source_fps,
        crf=quality.crf,
        preset=quality.preset,
        loudness_target_lufs=LOUDNORM_I if loudnorm else None,
        sources_used=edl.source_ids(),
    )


def _quick_silence_check(inputs: list[str], audio_graph: str, audio_label: str):
    """Cheap measurement used for draft and preview renders.

    Draft and preview do not need an accurate two-pass normalisation, but they
    do need to know whether the audio is silent, because that is what makes the
    encoder fail.
    """
    return measure_loudness(inputs, audio_graph, audio_label)


def expected_duration(edl: EDL) -> float:
    """What the output should be, for QA to compare against."""
    return Timeline(edl).duration


def fps_float(rate: str) -> float:
    return float(Fraction(rate))
