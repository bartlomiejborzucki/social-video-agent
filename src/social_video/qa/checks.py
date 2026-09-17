"""Mechanical checks on a rendered file.

These run first and are cheap, deterministic, and able to detect things a
vision model cannot reliably see: a 40 ms silence at a splice, a two-frame
black flash, true-peak clipping, a duration that drifted from the EDL.

Visual inspection is still valuable, but it is aimed at what these checks
flag rather than being the primary mechanism.
"""

from __future__ import annotations

import re
import statistics
import subprocess
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

import numpy as np

from social_video.edl.render import allocate_range_frames
from social_video.edl.timeline import Timeline
from social_video.errors import FFmpegError
from social_video.ffmpeg.filters import LOUDNORM_I
from social_video.ffmpeg.probe import parse_fps, probe
from social_video.ffmpeg.run import find_binary, run_ffmpeg, run_ffprobe_json
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.edl import EDL, VisualFillStrategy
from social_video.schemas.qa import QACheck, QAReport, QASeverity

#: How far the rendered duration may drift from the EDL before we complain.
#: Ranges are frame-aligned before rendering, so the only remaining slack is
#: container timestamp rounding. Two frames at 24 fps is generous.
DURATION_TOLERANCE = 0.045
#: True peak above this counts as clipping.
CLIP_CEILING_DB = -0.5
#: Loudness this far from target is worth reporting.
LOUDNESS_TOLERANCE = 2.0

_MAX_VOLUME = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_BLACK = re.compile(r"black_start:(\d+(?:\.\d+)?)\s+black_end:(\d+(?:\.\d+)?)")
_SILENCE_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


def check_render(
    output: Path,
    edl: EDL | None = None,
    *,
    captions: CaptionTrack | None = None,
    attempt: int = 1,
    max_attempts: int = 3,
) -> QAReport:
    """Inspect a rendered file and report what is wrong with it."""
    report = QAReport(
        output=str(output),
        edl=edl.name if edl else None,
        attempt=attempt,
        max_attempts=max_attempts,
    )

    if not output.is_file():
        report.checks.append(
            QACheck(
                name="output exists",
                severity=QASeverity.ERROR,
                passed=False,
                message=f"{output} was not produced",
            )
        )
        return report

    info = probe(output)
    report.checks.append(
        QACheck(
            name="output exists",
            severity=QASeverity.INFO,
            passed=True,
            message=f"{output.name}, {info.size_bytes / 1e6:.1f} MB",
        )
    )

    _check_streams(report, info, edl)
    _check_duration(report, info, edl)
    _check_audio(report, output, info)
    _check_decode(report, output)
    _check_ending_visual_continuity(report, output, info, edl)
    _check_black_frames(report, output, info)
    if edl is not None:
        _check_cut_boundaries(report, output, edl)
    if captions is not None:
        _check_captions(report, captions, info)
    if edl is not None and edl.accepted_qa_warnings:
        accepted = set(edl.accepted_qa_warnings)
        for check in report.checks:
            if check.severity is QASeverity.WARNING and check.name in accepted:
                check.accepted = True
    return report


def _check_streams(report: QAReport, info, edl: EDL | None) -> None:
    video = info.video
    if video is None:
        report.checks.append(
            QACheck(
                name="video stream",
                severity=QASeverity.ERROR,
                passed=False,
                message="the output has no video stream",
            )
        )
        return
    w, h = video.display_size
    report.checks.append(
        QACheck(
            name="resolution",
            severity=QASeverity.INFO,
            passed=True,
            message=f"{w}x{h} @ {video.fps_float:.3f} fps ({video.pix_fmt})",
        )
    )
    expected_rate = (
        parse_fps(edl.output_fps) if edl and edl.output_fps else video.nominal_frame_rate
    )
    actual_nominal = parse_fps(video.nominal_frame_rate)
    actual_average = Fraction(video.frame_rate)
    nominal = Fraction(actual_nominal)
    standard = actual_nominal in {"30/1", "60/1", "30000/1001", "60000/1001"}
    cfr = abs(float(actual_average - nominal)) <= max(0.001, float(nominal) * 0.0001)
    expected_ok = actual_nominal == expected_rate if edl and edl.output_fps else standard
    ok = cfr and expected_ok
    report.checks.append(
        QACheck(
            name="constant standard frame rate",
            severity=QASeverity.ERROR if not ok else QASeverity.INFO,
            passed=ok,
            message=(
                f"avg={video.frame_rate}, nominal={video.nominal_frame_rate}, "
                f"time_base={video.time_base or 'unknown'}"
            ),
            measured=float(actual_average),
            expected=float(Fraction(expected_rate)),
        )
    )
    compatible = video.codec == "h264" and video.pix_fmt == "yuv420p"
    report.checks.append(
        QACheck(
            name="social video codec",
            severity=QASeverity.ERROR if not compatible else QASeverity.INFO,
            passed=compatible,
            message=f"{video.codec}, {video.pix_fmt}",
        )
    )
    if w % 2 or h % 2:
        report.checks.append(
            QACheck(
                name="even dimensions",
                severity=QASeverity.ERROR,
                passed=False,
                message=f"{w}x{h} is not divisible by 2, which yuv420p requires",
            )
        )


def _check_duration(report: QAReport, info, edl: EDL | None) -> None:
    if edl is None:
        return
    if info.video is not None:
        rate = info.video.nominal_frame_rate
        expected = sum(allocate_range_frames(edl, rate)) / float(Fraction(rate))
    else:
        expected = Timeline(edl).duration
    drift = abs(info.duration - expected)
    ok = drift <= DURATION_TOLERANCE
    report.checks.append(
        QACheck(
            name="duration matches EDL",
            severity=QASeverity.ERROR if not ok else QASeverity.INFO,
            passed=ok,
            message=(
                f"rendered {info.duration:.3f}s, EDL expects {expected:.3f}s "
                f"(drift {drift * 1000:.0f}ms)"
            ),
            measured=info.duration,
            expected=expected,
        )
    )


def _check_audio(report: QAReport, output: Path, info) -> None:
    if not info.has_audio:
        report.checks.append(
            QACheck(
                name="audio present",
                severity=QASeverity.ERROR,
                passed=False,
                message="the output has no audio stream",
            )
        )
        return

    audio = info.audio[0]
    format_ok = (
        audio.codec == "aac"
        and audio.sample_rate == 48000
        and audio.channels == 2
        and audio.channel_layout in {"stereo", "2 channels", ""}
    )
    report.checks.append(
        QACheck(
            name="social audio format",
            severity=QASeverity.ERROR if not format_ok else QASeverity.INFO,
            passed=format_ok,
            message=(
                f"{audio.codec} {audio.profile or ''}, {audio.sample_rate} Hz, "
                f"{audio.channels}ch {audio.channel_layout}, "
                f"time_base={audio.time_base or 'unknown'}"
            ).strip(),
        )
    )

    packet_data = run_ffprobe_json(
        [
            "-select_streams",
            "a:0",
            "-show_packets",
            "-show_entries",
            "packet=pts_time,duration_time",
            str(output),
        ],
        desc="inspect audio packet timestamps",
        timeout=1800,
    )
    packets = packet_data.get("packets") or []
    timed_packets = [
        (float(packet["pts_time"]), float(packet.get("duration_time") or 0.0))
        for packet in packets
        if packet.get("pts_time") is not None
    ]
    pts = [packet_pts for packet_pts, _ in timed_packets]
    monotonic = len(pts) >= 2 and all(b > a for a, b in pairwise(pts))
    report.checks.append(
        QACheck(
            name="audio PTS monotonic",
            severity=QASeverity.ERROR if not monotonic else QASeverity.INFO,
            passed=monotonic,
            message=f"{len(pts)} packet timestamp(s)",
        )
    )
    deltas = [b - a for a, b in pairwise(pts) if b > a]
    cadence = statistics.median(deltas) if deltas else 0.0
    expected_cadence = 1024 / 48000
    cadence_ok = abs(cadence - expected_cadence) <= 0.002
    report.checks.append(
        QACheck(
            name="AAC packet cadence",
            severity=QASeverity.ERROR if not cadence_ok else QASeverity.INFO,
            passed=cadence_ok,
            message=f"median {cadence * 1000:.3f}ms; expected {expected_cadence * 1000:.3f}ms",
            measured=cadence,
            expected=expected_cadence,
        )
    )
    packet_end = max((packet_pts + duration for packet_pts, duration in timed_packets), default=0.0)
    video_duration = info.video.duration if info.video and info.video.duration else info.duration
    # At most two AAC-LC frames. A video-frame-sized tolerance would let the
    # very timestamp corruption this check exists for slip through short clips.
    tolerance = 2 * expected_cadence + 0.001
    audio_duration = packet_end - min(0.0, pts[0]) if pts else (audio.duration or 0.0)
    duration_ok = abs(audio_duration - video_duration) <= tolerance
    container_ok = abs(audio_duration - info.duration) <= tolerance
    report.checks.append(
        QACheck(
            name="audio timeline duration",
            severity=QASeverity.ERROR if not (duration_ok and container_ok) else QASeverity.INFO,
            passed=duration_ok and container_ok,
            message=(
                f"audio packets {audio_duration:.3f}s, video {video_duration:.3f}s, "
                f"container {info.duration:.3f}s"
            ),
            measured=audio_duration,
            expected=video_duration,
        )
    )

    stderr = run_ffmpeg(
        ["-i", str(output), "-af", "volumedetect", "-f", "null", "-"],
        desc="measure output level",
        timeout=1800,
    )
    peak = float(m.group(1)) if (m := _MAX_VOLUME.search(stderr)) else None
    mean = float(m.group(1)) if (m := _MEAN_VOLUME.search(stderr)) else None

    audible = mean is not None and mean > -60.0
    report.checks.append(
        QACheck(
            name="audio present",
            severity=QASeverity.ERROR if not audible else QASeverity.INFO,
            passed=audible,
            message=(
                f"peak {peak:.1f} dBFS, mean {mean:.1f} dBFS"
                if peak is not None
                else "level could not be measured"
            ),
            measured=mean,
        )
    )

    if peak is not None:
        clipped = peak > CLIP_CEILING_DB
        report.checks.append(
            QACheck(
                name="no clipping",
                severity=QASeverity.WARNING,
                passed=not clipped,
                message=(
                    f"peak {peak:.1f} dBFS exceeds {CLIP_CEILING_DB} dBFS"
                    if clipped
                    else f"peak {peak:.1f} dBFS"
                ),
                measured=peak,
                expected=CLIP_CEILING_DB,
            )
        )


def _check_decode(report: QAReport, output: Path) -> None:
    try:
        run_ffmpeg(
            [
                "-v",
                "error",
                "-i",
                str(output),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-f",
                "null",
                "-",
            ],
            desc="fully decode output streams",
            timeout=3600,
        )
    except FFmpegError as exc:
        report.checks.append(
            QACheck(
                name="full stream decode",
                severity=QASeverity.ERROR,
                passed=False,
                message=str(exc),
            )
        )
    else:
        report.checks.append(
            QACheck(
                name="full stream decode",
                severity=QASeverity.INFO,
                passed=True,
                message="video and audio decoded to null without errors",
            )
        )


def _check_ending_visual_continuity(report: QAReport, output: Path, info, edl: EDL | None) -> None:
    """Detect truly repeated decoded frames near the end, not merely low motion."""
    interval = 0.25
    begin = max(0.0, info.duration - 10.0)
    frame_size = 64 * 64
    argv = [
        find_binary("ffmpeg"),
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-ss",
        f"{begin:.6f}",
        "-i",
        str(output),
        "-vf",
        f"fps={1 / interval},scale=64:64:flags=area,format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    proc = subprocess.run(argv, capture_output=True, check=False, timeout=1800)
    if proc.returncode != 0:
        report.checks.append(
            QACheck(
                name="ending visual continuity",
                severity=QASeverity.ERROR,
                passed=False,
                message="could not sample ending frames for continuity analysis",
            )
        )
        return
    count = len(proc.stdout) // frame_size
    frames = [
        np.frombuffer(proc.stdout[index * frame_size : (index + 1) * frame_size], dtype=np.uint8)
        for index in range(count)
    ]
    static_edges = [
        float(np.mean(np.abs(right.astype(np.int16) - left.astype(np.int16)))) <= 0.5
        for left, right in pairwise(frames)
    ]
    best_start = 0
    best_edges = 0
    run_start = 0
    run_edges = 0
    for index, unchanged in enumerate(static_edges):
        if unchanged:
            if run_edges == 0:
                run_start = index
            run_edges += 1
            if run_edges > best_edges:
                best_start, best_edges = run_start, run_edges
        else:
            run_edges = 0
    static_start = begin + best_start * interval
    static_duration = best_edges * interval
    static_end = min(info.duration, static_start + static_duration)
    if best_edges and best_start + best_edges == len(static_edges):
        # The last sample represents a hold that continues to the file end;
        # account for the unsampled tail instead of under-reporting one bucket.
        static_end = info.duration
        static_duration = static_end - static_start
    approved = _static_span_is_approved(edl, static_start, static_end)
    blocked = static_duration > 1.0 and not approved
    if approved:
        detail = "explicitly approved in the EDL"
    elif static_duration > 0:
        detail = "not explicitly approved"
    else:
        detail = "no repeated-frame run detected"
    report.checks.append(
        QACheck(
            name="ending visual continuity",
            severity=QASeverity.ERROR if blocked else QASeverity.INFO,
            passed=not blocked,
            message=(
                f"longest near-identical span {static_duration:.2f}s "
                f"({static_start:.2f}-{static_end:.2f}s); {detail}"
            ),
            at=static_start if static_duration else None,
            measured=static_duration,
            expected=1.0,
            accepted=approved,
        )
    )


def _static_span_is_approved(edl: EDL | None, start: float, end: float) -> bool:
    if edl is None:
        return False
    timeline = Timeline(edl)
    for item in timeline.slices:
        rng = item.range
        approved_duration = 0.0
        if rng.visual_fill_strategy is VisualFillStrategy.FREEZE and rng.intentional_hold:
            approved_duration = rng.freeze_duration or 0.0
        elif rng.visual_fill_strategy is VisualFillStrategy.END_CARD:
            approved_duration = rng.declared_visual_fill_duration
        if approved_duration <= 0:
            continue
        approved_start = item.output_end - approved_duration
        if start >= approved_start - 0.3 and end <= item.output_end + 0.3:
            return True
    return False


def _check_black_frames(report: QAReport, output: Path, info) -> None:
    """Unexpected black is nearly always a bad cut or a bad crop."""
    stderr = run_ffmpeg(
        ["-i", str(output), "-vf", "blackdetect=d=0.05:pic_th=0.98", "-f", "null", "-"],
        desc="detect black frames",
        timeout=1800,
    )
    spans = [(float(a), float(b)) for a, b in _BLACK.findall(stderr)]
    # Black at the very start or end is usually deliberate (a fade); black in
    # the middle is not.
    interior = [(a, b) for a, b in spans if a > 0.25 and b < max(0.0, info.duration - 0.25)]
    report.checks.append(
        QACheck(
            name="no black frames mid-timeline",
            severity=QASeverity.WARNING,
            passed=not interior,
            message=(
                "none detected"
                if not interior
                else "black at " + ", ".join(f"{a:.2f}-{b:.2f}s" for a, b in interior[:5])
            ),
            at=interior[0][0] if interior else None,
        )
    )


def _check_cut_boundaries(report: QAReport, output: Path, edl: EDL) -> None:
    """Look for silence straddling a splice.

    A pop is hard to measure directly, but its common causes -- a dropped
    sample run or a fade that swallowed real speech -- show up as a short
    silence exactly at a boundary, which is cheap to detect and unambiguous.
    """
    boundaries = Timeline(edl).cut_boundaries()
    if not boundaries:
        return

    stderr = run_ffmpeg(
        ["-i", str(output), "-af", "silencedetect=noise=-45dB:d=0.12", "-f", "null", "-"],
        desc="detect silence at cuts",
        timeout=1800,
    )
    starts = [float(x) for x in _SILENCE_START.findall(stderr)]
    ends = [float(x) for x in _SILENCE_END.findall(stderr)]
    silences = list(zip(starts, ends, strict=False))

    suspicious = [
        b for b in boundaries if any(start - 0.15 <= b <= end + 0.15 for start, end in silences)
    ]
    report.checks.append(
        QACheck(
            name="cut boundaries carry audio",
            severity=QASeverity.WARNING,
            passed=not suspicious,
            message=(
                f"{len(boundaries)} boundary/boundaries, all carry audio"
                if not suspicious
                else "silence detected at cut(s) " + ", ".join(f"{b:.2f}s" for b in suspicious[:5])
            ),
            at=suspicious[0] if suspicious else None,
        )
    )


def _check_captions(report: QAReport, captions: CaptionTrack, info) -> None:
    overlaps = captions.overlapping()
    report.checks.append(
        QACheck(
            name="captions do not overlap",
            severity=QASeverity.WARNING,
            passed=not overlaps,
            message="none" if not overlaps else f"{len(overlaps)} overlapping pair(s)",
        )
    )
    past_end = [c for c in captions.cues if c.start > info.duration + 0.05]
    report.checks.append(
        QACheck(
            name="captions inside the timeline",
            severity=QASeverity.WARNING,
            passed=not past_end,
            message=(
                "all cues land inside the output"
                if not past_end
                else f"{len(past_end)} cue(s) start after the video ends"
            ),
            at=past_end[0].start if past_end else None,
        )
    )


def loudness_comment(measured: float | None) -> str:
    """Describe measured loudness against the social target."""
    if measured is None:
        return "not measured"
    delta = measured - LOUDNORM_I
    if abs(delta) <= LOUDNESS_TOLERANCE:
        return f"{measured:.1f} LUFS, on target"
    direction = "louder" if delta > 0 else "quieter"
    return f"{measured:.1f} LUFS, {abs(delta):.1f} LU {direction} than target"
