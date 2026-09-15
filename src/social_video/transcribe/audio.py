"""Audio extraction and measurement for transcription."""

from __future__ import annotations

import re
from pathlib import Path

from social_video.errors import SocialVideoError
from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import run_ffmpeg

#: Below this peak the track carries no usable speech. Guarding on it stops us
#: spending minutes of GPU time, or a paid API call, on a silent track.
SILENCE_PEAK_DBFS = -60.0


def extract_audio(source: Path, dest: Path, *, audio_track: int = 0) -> Path:
    """Extract one audio track as mono 16 kHz PCM, which is what ASR wants."""
    info = probe(source)
    if not info.audio:
        raise SocialVideoError(f"{source.name} has no audio track, so it cannot be transcribed.")
    if audio_track >= len(info.audio):
        raise SocialVideoError(
            f"{source.name} has {len(info.audio)} audio track(s); track {audio_track} "
            f"was requested. Tracks are zero-based."
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-y",
            "-i",
            str(source),
            "-map",
            f"0:a:{audio_track}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ],
        desc=f"extract audio track {audio_track} from {source.name}",
        timeout=3600,
    )
    return dest


_MAX_VOLUME = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def peak_dbfs(audio: Path) -> float:
    """Peak level of a WAV, in dBFS.

    Measured with ffmpeg's ``volumedetect`` rather than by parsing samples in
    Python: it is faster, and it avoids upstream's assumption that the host is
    little-endian and the samples are 16-bit.
    """
    stderr = run_ffmpeg(
        ["-i", str(audio), "-af", "volumedetect", "-f", "null", "-"],
        desc=f"measure level of {audio.name}",
        timeout=1800,
    )
    match = _MAX_VOLUME.search(stderr)
    if not match:
        # Unparseable output should not silently read as "loud enough".
        return float("-inf")
    return float(match.group(1))


def guard_not_silent(audio: Path, *, source_name: str, audio_track: int) -> float:
    """Raise if a track is effectively silent, naming the likely cause."""
    peak = peak_dbfs(audio)
    if peak < SILENCE_PEAK_DBFS:
        raise SocialVideoError(
            f"audio track {audio_track} of {source_name} is silent "
            f"(peak {peak:.1f} dBFS). If this is a multi-track recording, the speech "
            f"is probably on another track -- try --audio-track 1."
        )
    return peak
