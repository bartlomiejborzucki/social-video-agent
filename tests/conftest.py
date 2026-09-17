"""Shared fixtures.

Media is generated with ffmpeg at test time rather than committed. Video files
do not belong in git, and a generated fixture is explicit about exactly what it
contains.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HAS_FFMPEG = shutil.which("ffmpeg") is not None
requires_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


def ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-nostdin", "-y", *args],
        check=True,
        capture_output=True,
    )


def make_video(
    path: Path,
    *,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    duration: float = 3.0,
    audio: bool = True,
    audio_channels: int = 1,
    rotation: int | None = None,
) -> Path:
    """Generate a test video with a colour pattern and a tone."""
    path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={width}x{height}:rate={fps}:duration={duration}",
    ]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
    if audio:
        args += ["-c:a", "aac", "-ac", str(audio_channels), "-shortest"]
    else:
        args += ["-an"]
    if rotation is not None:
        # Written as display-matrix metadata, which is how phones record
        # orientation and what the decoder autorotates from.
        args += ["-metadata:s:v:0", f"rotate={rotation}"]
    args += [str(path)]
    ffmpeg(*args)
    return path


def make_silent_video(path: Path, *, duration: float = 2.0) -> Path:
    """Video with an audio track that contains nothing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s=320x240:rate=25:duration={duration}",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r=44100:cl=mono:d={duration}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    )
    return path


def make_multitrack_video(path: Path, *, duration: float = 2.0) -> Path:
    """Two audio tracks: silence on track 0, a tone on track 1.

    This is the shape of an OBS recording, where desktop audio lands on track 0
    and the microphone on track 1 -- so transcribing track 0 by default
    transcribes the wrong thing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=320x240:rate=25:duration={duration}",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r=44100:cl=stereo:d={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-map",
        "2:a",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    )
    return path


@pytest.fixture
def landscape(tmp_path):
    return make_video(tmp_path / "landscape.mp4", width=1280, height=720)


@pytest.fixture
def portrait(tmp_path):
    return make_video(tmp_path / "portrait.mp4", width=720, height=1280)


@pytest.fixture
def sixty_fps(tmp_path):
    return make_video(tmp_path / "60fps.mp4", fps=60, duration=2.0)


@pytest.fixture
def rotated(tmp_path):
    return make_video(tmp_path / "rotated.mp4", width=1280, height=720, rotation=90)


@pytest.fixture
def no_audio(tmp_path):
    return make_video(tmp_path / "silent.mp4", audio=False, duration=2.0)
