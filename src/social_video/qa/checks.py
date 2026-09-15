"""Mechanical checks on a rendered file.

These run first and are cheap, deterministic, and able to detect things a
vision model cannot reliably see: a 40 ms silence at a splice, a two-frame
black flash, true-peak clipping, a duration that drifted from the EDL.

Visual inspection is still valuable, but it is aimed at what these checks
flag rather than being the primary mechanism.
"""

from __future__ import annotations

import re
from pathlib import Path

from social_video.edl.timeline import Timeline
from social_video.ffmpeg.filters import LOUDNORM_I
from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import run_ffmpeg
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.edl import EDL
from social_video.schemas.qa import QACheck, QAReport, QASeverity

#: How far the rendered duration may drift from the EDL before we complain.
#: One frame at 24 fps is ~42 ms; encoders legitimately round to frame edges.
DURATION_TOLERANCE = 0.12
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
    _check_black_frames(report, output, info)
    if edl is not None:
        _check_cut_boundaries(report, output, edl)
    if captions is not None:
        _check_captions(report, captions, info)
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
