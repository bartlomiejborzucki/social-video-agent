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
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

from social_video.edl.loudness import loudnorm_filter, measure_loudness
from social_video.edl.timeline import Timeline
from social_video.edl.validate import validate_edl
from social_video.edl.voice import NO_CLEANUP, VoiceCleanup, measure_voice, plan_cleanup
from social_video.errors import ValidationError
from social_video.ffmpeg.filters import (
    LOUDNORM_I,
    TONEMAP_CHAIN,
    audio_cut_fades,
    crop_position_expression,
    escape_filter_path,
)
from social_video.ffmpeg.probe import (
    MediaInfo,
    probe,
    resolve_output_fps,
)
from social_video.ffmpeg.run import has_libass, has_libzimg, run_ffmpeg
from social_video.fsutil import atomic_copy, utc_timestamp
from social_video.paths import app_home
from social_video.schemas.edl import EDL, EDLRange, ReframeMode, VisualFillStrategy
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


@dataclass(frozen=True)
class RenderRange:
    video_input: int
    audio_input: int | None
    video_info: MediaInfo
    audio_info: MediaInfo
    fill_input: int | None
    fill_info: MediaInfo | None
    target_frames: int
    target_duration: float


#: One cloned frame of headroom before a range is trimmed to its exact length.
#: Expressed in frames because tpad's duration form is rounded down by ffmpeg,
#: which turns "one frame" into "no frames" at some rates.
CLONE_HEADROOM_FRAMES = 1


def allocate_range_frames(edl: EDL, fps: str) -> list[int]:
    """Round cumulative boundaries, so per-cut rounding cannot accumulate."""
    rate = float(Fraction(fps))
    frames: list[int] = []
    cursor = 0.0
    previous = 0
    for rng in edl.ranges:
        cursor += rng.output_duration
        boundary = max(previous + 1, round(cursor * rate))
        frames.append(boundary - previous)
        previous = boundary
    return frames


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
    rng: EDLRange,
    info: MediaInfo,
    canvas: tuple[int, int],
    default: ReframeMode,
    *,
    force_fit: bool = False,
) -> str:
    """Geometry for one range: crop if asked, then fit onto the canvas."""
    out_w, out_h = canvas
    plan = None if force_fit else rng.reframe
    mode = ReframeMode.FIT if force_fit else (plan.mode if plan else default)

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

    if rng.zoom > 1.0 and not force_fit:
        # A punch-in is a centred crop by 1/zoom, applied before the final scale
        # so it costs no resolution beyond the zoom itself.
        z = rng.zoom
        parts.append(f"crop=iw/{z:.4f}:ih/{z:.4f}:(iw-iw/{z:.4f})/2:(ih-ih/{z:.4f})/2")

    parts.append(f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos")
    parts.append(f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black")
    parts.append("setsar=1")
    return ",".join(parts)


@dataclass(frozen=True)
class AudioMix:
    """Where the music bed and sound effects landed in the input list."""

    bed_input: int | None = None
    sfx_inputs: tuple[int, ...] = ()

    @property
    def active(self) -> bool:
        return self.bed_input is not None or bool(self.sfx_inputs)


def build_speech_graph(edl: EDL, ranges: list[RenderRange]) -> tuple[str, str]:
    """The cut speech alone: no bed, no effects, no cleanup, no normalisation.

    This is what voice cleanup measures. Measuring the finished mix instead
    would describe the music as if it were room noise.
    """
    parts: list[str] = []
    labels: list[str] = []
    for index, (rng, media) in enumerate(zip(edl.ranges, ranges, strict=True)):
        parts.append(_audio_chain(index, rng, media))
        labels.append(f"[a{index}]")
    parts.append(f"{''.join(labels)}concat=n={len(edl.ranges)}:v=0:a=1[ca]")
    total = sum(media.target_duration for media in ranges)
    parts.append(f"[ca]{_final_audio_chain(total)}[cam]")
    return ";".join(parts), "[cam]"


def build_audio_graph(
    edl: EDL,
    ranges: list[RenderRange],
    mix: AudioMix | None = None,
    *,
    cleanup: str | None = None,
) -> tuple[str, str]:
    """Build only the audio half of the graph, for the measurement pass.

    Identical to what the render will do to the audio, so the measurement
    describes the audio that will actually be produced -- including the music
    bed, which changes the integrated loudness it is measuring, and the voice
    cleanup, which changes it too.
    """
    speech, label = build_speech_graph(edl, ranges)
    parts = [speech]
    total = sum(media.target_duration for media in ranges)
    if cleanup:
        # Cleanup sits on the speech, before the bed: denoising a mix would
        # treat the music as noise, and compressing it would pump with it.
        parts.append(f"{label}{cleanup}[acleaned]")
        label = "[acleaned]"
    label = _mix_music_and_effects(parts, label, edl, mix, total)
    return ";".join(parts), label


def _mix_music_and_effects(
    parts: list[str],
    label: str,
    edl: EDL,
    mix: AudioMix | None,
    duration: float,
) -> str:
    """Mix the bed under the speech, duck it, and place explicit effects.

    The bed is ducked by sidechaining the speech into a compressor rather than
    by a static volume automation curve, so it gets out of the way of whatever
    the speaker actually does instead of of where we guessed they would pause.
    """
    if mix is None or not mix.active:
        return label
    bed = edl.audio_bed
    if bed is not None and mix.bed_input is not None:
        chain = [
            "aresample=48000:async=1:first_pts=0",
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo",
            f"apad=whole_dur={duration:.9f}",
            f"atrim=duration={duration:.9f}",
            "asetpts=N/SR/TB",
            f"volume={bed.gain_db:.2f}dB",
        ]
        if bed.fade_in > 0:
            chain.append(f"afade=t=in:st=0:d={min(bed.fade_in, duration):.3f}")
        if bed.fade_out > 0:
            start = max(0.0, duration - bed.fade_out)
            chain.append(f"afade=t=out:st={start:.3f}:d={min(bed.fade_out, duration):.3f}")
        parts.append(f"[{mix.bed_input}:a:0]{','.join(chain)}[bedp]")
        bed_label = "[bedp]"
        speech_label = label
        if bed.duck:
            parts.append(f"{label}asplit=2[spmain][spkey]")
            speech_label = "[spmain]"
            threshold = 10.0 ** (bed.duck_threshold_db / 20.0)
            parts.append(
                f"[bedp][spkey]sidechaincompress="
                f"threshold={threshold:.6f}:ratio={bed.duck_ratio:.2f}:"
                f"attack=20:release={bed.duck_release_ms}:level_sc=1[bedd]"
            )
            bed_label = "[bedd]"
        parts.append(
            f"{speech_label}{bed_label}"
            "amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amixed]"
        )
        label = "[amixed]"
    if mix.sfx_inputs:
        effect_labels: list[str] = []
        for number, (effect, input_index) in enumerate(
            zip(edl.sound_effects, mix.sfx_inputs, strict=True)
        ):
            delay = max(0, round(effect.at * 1000))
            parts.append(
                f"[{input_index}:a:0]"
                "aresample=48000:async=1:first_pts=0,"
                "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                f"volume={effect.gain_db:.2f}dB,"
                f"adelay={delay}|{delay},"
                f"atrim=duration={duration:.9f},asetpts=N/SR/TB[sfx{number}]"
            )
            effect_labels.append(f"[sfx{number}]")
        parts.append(
            f"{label}{''.join(effect_labels)}"
            f"amix=inputs={len(effect_labels) + 1}:duration=first:"
            "dropout_transition=0:normalize=0[awithsfx]"
        )
        label = "[awithsfx]"
    if not edl.normalize_audio:
        # Without the loudnorm pass nothing else limits the summed peaks, and a
        # mix is exactly where clipping appears.
        parts.append(f"{label}alimiter=limit=0.891[alimited]")
        label = "[alimited]"
    parts.append(f"{label}{_final_audio_chain(duration)}[amixout]")
    return "[amixout]"


def _audio_chain(index: int, rng: EDLRange, media: RenderRange) -> str:
    """The per-range audio chain, shared by the measurement and render passes."""
    target = media.target_duration
    if media.audio_input is None or not media.audio_info.has_audio:
        # A silent range still needs an audio stream or concat refuses. The
        # explicit duration and aformat matter: without them the generated
        # stream can reach the encoder with an unexpected sample format.
        return (
            f"anullsrc=r=48000:cl=stereo:d={target:.9f},"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"asettb=1/48000,asetpts=N/SR/TB[a{index}]"
        )
    # Render the same track that was transcribed. Mapping 0:a:0 unconditionally
    # is what makes a multi-track recording come out silent: OBS puts desktop
    # audio on track 0 and the microphone on track 1.
    track = min(rng.audio_track, max(0, len(media.audio_info.audio) - 1))
    chain: list[str] = [
        f"atrim=duration={rng.audio_duration:.9f}",
        "aresample=48000:async=1:first_pts=0",
        "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo",
        "asettb=1/48000",
        "asetpts=N/SR/TB",
    ]
    if rng.speed != 1.0:
        chain.extend(_atempo_chain(rng.speed))
    if rng.audio_gain_db:
        chain.append(f"volume={rng.audio_gain_db:.2f}dB")
    # Short fades at both edges prevent the click that a hard splice makes.
    chain.extend(
        [
            f"apad=whole_dur={target:.9f}",
            f"atrim=duration={target:.9f}",
            audio_cut_fades(target),
            "aresample=48000:async=1:first_pts=0",
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo",
            "asettb=1/48000",
            "asetpts=N/SR/TB",
        ]
    )
    return f"[{media.audio_input}:a:{track}]{','.join(chain)}[a{index}]"


def _final_audio_chain(duration: float) -> str:
    return ",".join(
        [
            "aresample=48000:async=1:first_pts=0",
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo",
            f"apad=whole_dur={duration:.9f}",
            f"atrim=duration={duration:.9f}",
            "asettb=1/48000",
            "asetpts=N/SR/TB",
        ]
    )


def _fill_source(rng: EDLRange) -> tuple[str, float, float] | None:
    if rng.visual_fill_strategy is VisualFillStrategy.SECONDARY_VIDEO:
        assert rng.secondary_video_source is not None
        assert rng.secondary_video_start is not None
        assert rng.secondary_video_end is not None
        return rng.secondary_video_source, rng.secondary_video_start, rng.secondary_video_end
    if rng.visual_fill_strategy is VisualFillStrategy.END_CARD:
        assert rng.end_card_source is not None
        assert rng.end_card_start is not None
        assert rng.end_card_end is not None
        return rng.end_card_source, rng.end_card_start, rng.end_card_end
    return None


def _fill_source_duration(rng: EDLRange) -> float:
    fill = _fill_source(rng)
    return 0.0 if fill is None else fill[2] - fill[1]


def build_filtergraph(
    edl: EDL,
    ranges: list[RenderRange],
    *,
    canvas: tuple[int, int],
    fps: str,
    caption_file: Path | None,
    loudnorm: str | None,
    mix: AudioMix | None = None,
    cleanup: str | None = None,
) -> tuple[str, str, str]:
    """Build the whole filter graph. Returns (graph, video_label, audio_label)."""
    video_labels: list[str] = []
    audio_labels: list[str] = []
    parts: list[str] = []

    for index, (rng, media) in enumerate(zip(edl.ranges, ranges, strict=True)):
        vin = f"{media.video_input}:v:0"

        vchain: list[str] = []
        if media.video_info.video and media.video_info.video.is_hdr and has_libzimg():
            vchain.append(TONEMAP_CHAIN)
        visual_duration = rng.visual_content_end - rng.effective_video_start
        vchain.append(f"trim=duration={visual_duration:.9f}")
        vchain.append("setpts=PTS-STARTPTS")
        vchain.append(_reframe_filter(rng, media.video_info, canvas, edl.default_reframe))
        if rng.speed != 1.0:
            vchain.append(f"setpts=PTS/{rng.speed:.6f}")
        vchain.append(f"fps={fps}")
        rate = float(Fraction(fps))
        primary_frames = min(
            media.target_frames,
            max(1, round(rng.primary_visual_output_duration * rate)),
        )
        vchain.append(f"tpad=stop_mode=clone:stop={CLONE_HEADROOM_FRAMES}")
        vchain.append(f"trim=end_frame={primary_frames}")
        vchain.append(f"setpts=N/({fps}*TB)")
        primary_label = f"[vp{index}]"
        parts.append(f"[{vin}]{','.join(vchain)}{primary_label}")

        fill_frames = media.target_frames - primary_frames
        if media.fill_input is not None and media.fill_info is not None and fill_frames > 0:
            fill_duration = _fill_source_duration(rng)
            fill_chain = [
                f"trim=duration={fill_duration:.9f}",
                "setpts=PTS-STARTPTS",
                _reframe_filter(
                    rng,
                    media.fill_info,
                    canvas,
                    ReframeMode.FIT,
                    force_fit=True,
                ),
            ]
            if rng.speed != 1.0:
                fill_chain.append(f"setpts=PTS/{rng.speed:.6f}")
            fill_chain.extend(
                [
                    f"fps={fps}",
                    f"tpad=stop_mode=clone:stop={CLONE_HEADROOM_FRAMES}",
                    f"trim=end_frame={fill_frames}",
                    f"setpts=N/({fps}*TB)",
                ]
            )
            fill_label = f"[vf{index}]"
            parts.append(f"[{media.fill_input}:v:0]{','.join(fill_chain)}{fill_label}")
            parts.append(f"{primary_label}{fill_label}concat=n=2:v=1:a=0[v{index}]")
        else:
            # Pad in whole frames, never in seconds. A duration of "0.033333333"
            # is a hair under 1/30, and ffmpeg 7 derives the pad length with a
            # floor, so a range needing exactly one cloned frame silently got
            # none and the output came out short. Frames are exact.
            remaining_frames = max(0, media.target_frames - primary_frames)
            parts.append(
                f"{primary_label}tpad=stop_mode=clone:stop={remaining_frames},"
                f"trim=end_frame={media.target_frames},setpts=N/({fps}*TB)[v{index}]"
            )
        video_labels.append(f"[v{index}]")

        parts.append(_audio_chain(index, rng, media))
        audio_labels.append(f"[a{index}]")

    pairs = "".join(v + a for v, a in zip(video_labels, audio_labels, strict=True))
    parts.append(f"{pairs}concat=n={len(edl.ranges)}:v=1:a=1[cv][ca]")
    total_frames = sum(media.target_frames for media in ranges)
    total_duration = sum(media.target_duration for media in ranges)
    parts.append(f"[cv]trim=end_frame={total_frames},setpts=N/({fps}*TB)[cvm]")
    parts.append(f"[ca]{_final_audio_chain(total_duration)}[cam]")

    vlabel = "[cvm]"
    speech_label = "[cam]"
    if cleanup:
        parts.append(f"{speech_label}{cleanup}[acleaned]")
        speech_label = "[acleaned]"
    alabel = _mix_music_and_effects(parts, speech_label, edl, mix, total_duration)

    for number, overlay in enumerate(edl.overlays):
        last_input = max(max(r.video_input, r.audio_input or 0, r.fill_input or 0) for r in ranges)
        src = f"{last_input + 1 + number}:v:0"
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
        parts.append(f"{alabel}{loudnorm},{_final_audio_chain(total_duration)}[an]")
        alabel = "[an]"

    return ";".join(parts), vlabel, alabel


def _music_inputs(edl: EDL, next_input: int, duration: float) -> tuple[AudioMix, list[str]]:
    """Add the bed and effect inputs, refusing a bed that cannot cover the edit."""
    if edl.audio_bed is None and not edl.sound_effects:
        return AudioMix(), []
    inputs: list[str] = []
    bed_input: int | None = None
    if edl.audio_bed is not None:
        bed = edl.audio_bed
        path = Path(bed.path).expanduser()
        if not path.is_file():
            raise ValueError(f"audio_bed file does not exist: {path}")
        available = max(0.0, probe(path).duration - bed.start_at)
        if not bed.loop and available + 0.05 < duration:
            raise ValueError(
                f"audio_bed covers {available:.2f}s from {bed.start_at:.2f}s but the edit is "
                f"{duration:.2f}s. Use a longer track, or set loop: true and accept the seam."
            )
        bed_input = next_input
        next_input += 1
        if bed.loop:
            inputs += ["-stream_loop", "-1"]
        inputs += ["-ss", f"{bed.start_at:.9f}", "-t", f"{duration:.9f}", "-i", str(path)]
    sfx_inputs: list[int] = []
    for effect in edl.sound_effects:
        path = Path(effect.path).expanduser()
        if not path.is_file():
            raise ValueError(f"sound effect file does not exist: {path}")
        sfx_inputs.append(next_input)
        next_input += 1
        inputs += ["-i", str(path)]
    return AudioMix(bed_input=bed_input, sfx_inputs=tuple(sfx_inputs)), inputs


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
    audio_cleanup_policy: str = "none",
) -> RenderManifest:
    """Render an EDL to a file. Returns a manifest describing what was made."""
    warnings = validate_edl(edl, manifest)
    for warning in warnings:
        log.warning("edl: %s", warning)

    video_infos = [
        probe(manifest.by_id(r.effective_video_source).resolved_path()) for r in edl.ranges
    ]
    canvas = _canvas_for(edl, quality)
    fps = resolve_output_fps(video_infos, edl.output_fps)
    source_fps = resolve_output_fps(video_infos, None)
    frame_counts = allocate_range_frames(edl, fps)
    rate = float(Fraction(fps))

    if caption_file is not None and not has_libass():
        log.warning(
            "this ffmpeg has no libass, so captions cannot be burned in; rendering without them"
        )
        caption_file = None

    measured = None

    inputs: list[str] = []
    render_ranges: list[RenderRange] = []
    next_input = 0
    for rng, video_info, frames in zip(edl.ranges, video_infos, frame_counts, strict=True):
        if video_info.video is None:
            raise ValueError(f"source {rng.effective_video_source!r} has no video stream")
        video_input = next_input
        next_input += 1
        visual_duration = rng.visual_content_end - rng.effective_video_start
        inputs += [
            "-ss",
            f"{rng.effective_video_start:.9f}",
            "-t",
            f"{visual_duration:.9f}",
            "-i",
            str(video_info.path),
        ]
        audio_info = probe(manifest.by_id(rng.effective_audio_source).resolved_path())
        audio_input: int | None = None
        if audio_info.has_audio:
            audio_input = next_input
            next_input += 1
            inputs += [
                "-ss",
                f"{rng.effective_audio_start:.9f}",
                "-t",
                f"{rng.audio_duration:.9f}",
                "-i",
                str(audio_info.path),
            ]
        fill_input: int | None = None
        fill_info: MediaInfo | None = None
        if fill := _fill_source(rng):
            fill_source, fill_start, fill_end = fill
            fill_info = probe(manifest.by_id(fill_source).resolved_path())
            if fill_info.video is None:
                raise ValueError(f"visual fill source {fill_source!r} has no video stream")
            fill_input = next_input
            next_input += 1
            inputs += [
                "-ss",
                f"{fill_start:.9f}",
                "-t",
                f"{fill_end - fill_start:.9f}",
                "-i",
                str(fill_info.path),
            ]
        render_ranges.append(
            RenderRange(
                video_input=video_input,
                audio_input=audio_input,
                video_info=video_info,
                audio_info=audio_info,
                fill_input=fill_input,
                fill_info=fill_info,
                target_frames=frames,
                target_duration=frames / rate,
            )
        )
    for overlay in edl.overlays:
        inputs += ["-i", str(overlay.file)]
    next_input += len(edl.overlays)

    total_output_duration = sum(frames / rate for frames in frame_counts)
    mix, mix_inputs = _music_inputs(edl, next_input, total_output_duration)
    inputs += mix_inputs

    cleanup = _plan_voice_cleanup(
        edl, render_ranges, inputs, policy=audio_cleanup_policy, quality=quality
    )
    loudnorm = None
    if edl.normalize_audio:
        # Measure before normalising. loudnorm emits NaN on digitally silent
        # input and the encoder then fails, which would kill any edit whose
        # selected material happens to be quiet. The measurement decodes audio
        # only, so it costs a fraction of the render it informs -- and it lets
        # loudnorm run in its accurate linear mode rather than guessing.
        audio_graph, audio_label = build_audio_graph(edl, render_ranges, mix, cleanup=cleanup.chain)
        if quality.two_pass_loudness:
            measured = measure_loudness(inputs, audio_graph, audio_label)
        else:
            measured = _quick_silence_check(inputs, audio_graph, audio_label)
        loudnorm = loudnorm_filter(measured)
        if loudnorm is None:
            log.info("selected audio is silent; skipping loudness normalisation")

    graph, vlabel, alabel = build_filtergraph(
        edl,
        render_ranges,
        canvas=canvas,
        fps=fps,
        caption_file=caption_file,
        loudnorm=loudnorm,
        mix=mix,
        cleanup=cleanup.chain,
    )

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = _render_staging_dir()
    staged = staging / f"{output.stem}-{uuid4().hex}.mp4"
    total_frames = sum(frame_counts)
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
        "-tag:v",
        "avc1",
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
        "-ac",
        "2",
        "-vsync",
        "cfr",
        "-r",
        fps,
        "-frames:v",
        str(total_frames),
        "-movflags",
        "+faststart",
        str(staged),
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
    try:
        run_ffmpeg(args, desc=f"render {output.name}", timeout=14400)
        rendered = probe(staged)
        run_ffmpeg(
            ["-v", "error", "-i", str(staged), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
            desc=f"decode validation for {output.name}",
            timeout=14400,
        )
        _publish_atomic(staged, output)
        rendered = probe(output)
    finally:
        staged.unlink(missing_ok=True)
    return RenderManifest(
        output=str(output),
        edl=edl.name,
        rendered_at=utc_timestamp(),
        duration=rendered.duration,
        width=canvas[0],
        height=canvas[1],
        frame_rate=fps,
        frame_rate_converted_from=None if fps == source_fps else source_fps,
        crf=quality.crf,
        preset=quality.preset,
        loudness_target_lufs=LOUDNORM_I if loudnorm else None,
        sources_used=edl.source_ids(),
        audio_bed_applied=(
            {
                "path": edl.audio_bed.path,
                "gain_db": edl.audio_bed.gain_db,
                "ducked": edl.audio_bed.duck,
                "looped": edl.audio_bed.loop,
                "license_confirmed": edl.audio_bed.license_confirmed,
            }
            if edl.audio_bed is not None and mix.bed_input is not None
            else {}
        ),
        sound_effects_applied=len(mix.sfx_inputs),
        audio_cleanup_policy=audio_cleanup_policy,
        audio_cleanup_applied=cleanup.evidence(),
    )


def _plan_voice_cleanup(
    edl: EDL,
    render_ranges: list[RenderRange],
    inputs: list[str],
    *,
    policy: str,
    quality: Quality,
) -> VoiceCleanup:
    """Measure the cut speech and decide the chain, or leave the audio alone.

    A failed measurement never silently becomes "no cleanup" under a
    `required` policy: the point of that policy is that the project expects the
    repair to have happened.
    """
    if policy == "none":
        return NO_CLEANUP
    speech_graph, speech_label = build_speech_graph(edl, render_ranges)
    lra = None
    if quality.two_pass_loudness and edl.normalize_audio:
        measured = measure_loudness(inputs, speech_graph, speech_label)
        lra = measured.input_lra if measured and not measured.is_silent else None
    measurement = measure_voice(inputs, speech_graph, speech_label, loudness_range_lu=lra)
    if measurement is None:
        if policy == "required":
            raise ValidationError(
                "audio_cleanup_policy is 'required', but this edit's speech could not be "
                "measured, so no repair can be justified. Set audio_cleanup_policy to "
                "'measured' to continue without the guarantee, or 'none' to render the "
                "audio exactly as recorded."
            )
        log.info("voice could not be measured; leaving the audio as recorded")
        return NO_CLEANUP
    plan = plan_cleanup(measurement)
    log.info("%s", plan.summary())
    return plan


def _publish_atomic(staged: Path, output: Path) -> None:
    """Copy across filesystems under a private name, then atomically publish."""
    atomic_copy(staged, output)


def _render_staging_dir() -> Path:
    """Return a writable Linux-side directory for unpublished renders."""
    preferred = app_home() / "render-staging"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "social-video-agent" / "render-staging"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


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
