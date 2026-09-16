"""Source media inspection.

Results are memoised per resolved path. Upstream video-use spawns two ffprobe
processes *per EDL segment* (``is_portrait_source`` + ``is_hdr_source``) with no
caching, so a 40-cut edit drawn from one file pays for 80 subprocesses.
"""

from __future__ import annotations

import argparse
import functools
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from social_video.errors import FFmpegError
from social_video.ffmpeg.filters import HDR_TRANSFERS
from social_video.ffmpeg.run import run_ffprobe_json
from social_video.paths import normalize_user_path


@dataclass(frozen=True)
class VideoStream:
    index: int
    codec: str
    width: int
    height: int
    #: Rotation in degrees from the display matrix, normalised to [0, 360).
    rotation: int
    #: Frame rate as an exact rational string, e.g. ``"30000/1001"``.
    #: Derived from ``avg_frame_rate``, which is the honest figure for a
    #: variable-frame-rate source.
    frame_rate: str
    #: The container's declared rate (``r_frame_rate``). For constant-frame-rate
    #: material this is exact, where ``avg_frame_rate`` carries the rounding of
    #: frame count over duration. Use this when checking our own output.
    nominal_frame_rate: str
    pix_fmt: str
    color_transfer: str
    nb_frames: int | None

    @property
    def display_size(self) -> tuple[int, int]:
        """Dimensions as the viewer sees them, after rotation is applied."""
        if self.rotation in (90, 270):
            return self.height, self.width
        return self.width, self.height

    @property
    def is_portrait(self) -> bool:
        w, h = self.display_size
        return h > w

    @property
    def is_hdr(self) -> bool:
        return self.color_transfer in HDR_TRANSFERS

    @property
    def fps_float(self) -> float:
        return float(Fraction(self.frame_rate))


@dataclass(frozen=True)
class AudioStream:
    index: int
    codec: str
    channels: int
    sample_rate: int
    language: str | None


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    duration: float
    size_bytes: int
    format_name: str
    video: VideoStream | None
    audio: tuple[AudioStream, ...]

    @property
    def has_audio(self) -> bool:
        return bool(self.audio)


def parse_fps(value: str) -> str:
    """Validate a frame-rate string and canonicalise it to an exact rational.

    Ported verbatim in behaviour from browser-use/video-use
    ``helpers/render.py:175-198`` (MIT, Copyright (c) 2026 Browser Use); the
    only change is raising :class:`ValueError` instead of
    ``argparse.ArgumentTypeError`` so the function is usable outside argparse.

    This is the strongest code in the upstream project and is kept as-is:
    exact rational handling (no float drift on 29.97), idempotent, bounded by
    the int32 limits of ``AVRational``, and length-capped against a pathological
    input.
    """
    text = str(value).strip()
    if len(text) > 32 or not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?|[0-9]+/[0-9]+)", text):
        raise ValueError(
            f"invalid frame rate {value!r}: expected a number like 30, 29.97, or 30000/1001"
        )
    try:
        rate = Fraction(text)
    except ZeroDivisionError as exc:
        raise ValueError(f"invalid frame rate {value!r}: denominator is zero") from exc
    if rate <= 0:
        raise ValueError(f"invalid frame rate {value!r}: must be positive")
    max_component = 2_147_483_647  # AVRational components are int32
    if rate.numerator > max_component or rate.denominator > max_component:
        raise ValueError(f"frame rate {value!r} precision or magnitude is too large")
    return f"{rate.numerator}/{rate.denominator}"


def parse_fps_arg(value: str) -> str:
    """argparse/typer-friendly wrapper around :func:`parse_fps`."""
    try:
        return parse_fps(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _normalise_rotation(stream: dict[str, Any]) -> int:
    """Extract display-matrix rotation, normalised to 0/90/180/270.

    Concept from browser-use/video-use ``helpers/render.py:135-172`` (MIT).
    Upstream deliberately reads ``side_data_list`` rather than the legacy
    ``tags.rotate``, because only the display matrix guarantees that the
    decoder autorotates; that reasoning is preserved here. Modified: upstream
    swallows probe failures and assumes landscape, and only distinguishes
    portrait from landscape. We return the actual angle so callers can also
    handle the 180-degree case.
    """
    rotation = 0.0
    for side_data in stream.get("side_data_list") or []:
        value = side_data.get("rotation")
        if value is not None:
            try:
                rotation = float(value)
            except (TypeError, ValueError):
                rotation = 0.0
            break
    # ffprobe reports counter-clockwise negatives; normalise into [0, 360).
    return round(rotation) % 360


def _nominal_frame_rate(stream: dict[str, Any]) -> str:
    """The container's declared rate, preferring ``r_frame_rate``."""
    for key in ("r_frame_rate", "avg_frame_rate"):
        raw = stream.get(key) or ""
        if raw and raw != "0/0":
            try:
                return parse_fps(raw)
            except ValueError:
                continue
    return "30/1"


def _pick_frame_rate(stream: dict[str, Any]) -> str:
    """Prefer ``avg_frame_rate`` over ``r_frame_rate``.

    From browser-use/video-use ``helpers/render.py:201-228`` (MIT). ``avg`` is
    the correct choice for variable-frame-rate phone footage, where ``r`` is the
    theoretical maximum rather than the real rate.
    """
    for key in ("avg_frame_rate", "r_frame_rate"):
        raw = stream.get(key) or ""
        if raw and raw != "0/0":
            try:
                return parse_fps(raw)
            except ValueError:
                continue
    return "30/1"


@functools.lru_cache(maxsize=128)
def _probe_cached(resolved: str, mtime_ns: int, size: int) -> MediaInfo:
    """Memoised probe.

    ``mtime_ns`` and ``size`` are part of the key so that re-exporting a source
    in place invalidates the entry instead of serving stale geometry.
    """
    data = run_ffprobe_json(
        ["-show_format", "-show_streams", resolved],
        desc=f"probe {Path(resolved).name}",
        timeout=120,
    )
    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    video: VideoStream | None = None
    audio: list[AudioStream] = []
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "video" and video is None:
            # Skip attached cover art, which presents as a video stream.
            if (stream.get("disposition") or {}).get("attached_pic"):
                continue
            nb = stream.get("nb_frames")
            video = VideoStream(
                index=int(stream.get("index", 0)),
                codec=str(stream.get("codec_name") or "unknown"),
                width=int(stream.get("width") or 0),
                height=int(stream.get("height") or 0),
                rotation=_normalise_rotation(stream),
                frame_rate=_pick_frame_rate(stream),
                nominal_frame_rate=_nominal_frame_rate(stream),
                pix_fmt=str(stream.get("pix_fmt") or "unknown"),
                color_transfer=str(stream.get("color_transfer") or ""),
                nb_frames=int(nb) if nb and str(nb).isdigit() else None,
            )
        elif kind == "audio":
            tags = stream.get("tags") or {}
            audio.append(
                AudioStream(
                    index=int(stream.get("index", 0)),
                    codec=str(stream.get("codec_name") or "unknown"),
                    channels=int(stream.get("channels") or 0),
                    sample_rate=int(stream.get("sample_rate") or 0),
                    language=tags.get("language"),
                )
            )

    try:
        duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0

    return MediaInfo(
        path=Path(resolved),
        duration=duration,
        size_bytes=int(fmt.get("size") or size),
        format_name=str(fmt.get("format_name") or "unknown"),
        video=video,
        audio=tuple(audio),
    )


def probe(path: str | Path) -> MediaInfo:
    """Inspect a media file. Raises rather than guessing when probing fails."""
    p = normalize_user_path(path, must_exist=True)
    if not p.is_file():
        raise FileNotFoundError(f"source is not a file: {p}")
    resolved = str(p)
    stat = p.stat()
    return _probe_cached(resolved, stat.st_mtime_ns, stat.st_size)


def clear_probe_cache() -> None:
    """Drop memoised probe results. Used by tests."""
    _probe_cached.cache_clear()


def resolve_output_fps(sources: list[MediaInfo], override: str | None = None) -> str:
    """Decide one frame rate for the whole render.

    Every segment must share a frame rate or the stream-copy concat drifts out
    of sync. Default behaviour preserves the source rate rather than forcing
    24 fps; where sources disagree, the highest rate wins so nothing is
    decimated. An explicit override always takes precedence.
    """
    if override:
        return parse_fps(override)
    rates = [s.video.frame_rate for s in sources if s.video]
    if not rates:
        return "30/1"
    return max(rates, key=lambda r: Fraction(r))


def probe_audio_track_count(path: str | Path) -> int:
    """How many audio tracks a source carries.

    Multi-track sources are common: OBS records desktop audio on track 0 and
    the microphone on track 1, so transcribing track 0 by default silently
    transcribes game audio.
    """
    try:
        return len(probe(path).audio)
    except (FFmpegError, FileNotFoundError):
        return 0


def frame_aligned_duration(duration: float, frame_rate: str) -> float:
    """Round a duration to a whole number of frames.

    ffmpeg's ``-t`` takes the ceiling of the requested duration in frames, so a
    range of 0.35s at 30 fps yields 11 frames rather than 10.5. Unaligned, that
    adds up to one frame per cut: a 20-cut edit drifts about a third of a
    second, and a long one drifts enough to be audible against its captions.

    Aligning each range first makes the rendered length exact and independent
    of how many cuts there are.
    """
    rate = float(Fraction(frame_rate))
    if rate <= 0:
        return duration
    frames = max(1, round(duration * rate))
    return frames / rate
