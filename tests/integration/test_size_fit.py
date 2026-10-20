"""Delivery under a size limit: smaller picture, the same sound."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from social_video.errors import ValidationError
from social_video.ffmpeg.probe import probe
from social_video.size_fit import fit_to_size, video_bitrate_for
from tests.conftest import ffmpeg, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _audio_md5(path: Path) -> str:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "s16le", "-"],
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.md5(raw).hexdigest()


def _heavy(path: Path, seconds: int = 6) -> Path:
    picture = f"testsrc2=size=640x1136:rate=30:duration={seconds},noise=alls=60:allf=t"
    sound = f"aevalsrc='0.4*sin(2*PI*300*t)*lt(mod(t,0.7),0.3)':s=48000:d={seconds}"
    ffmpeg(
        "-f", "lavfi", "-i", picture,
        "-f", "lavfi", "-i", sound,
        "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(path),
    )  # fmt: skip
    return path


def test_an_oversized_video_is_reencoded_under_the_limit_with_its_audio_copied(
    tmp_path: Path,
) -> None:
    video = _heavy(tmp_path / "final.mp4")
    before = probe(video)
    sound = _audio_md5(video)
    limit = 1_500_000
    assert video.stat().st_size > limit
    fit = fit_to_size(video, limit)
    assert fit.reencoded and fit.after_bytes <= limit
    assert video.stat().st_size == fit.after_bytes
    after = probe(video)
    assert after.video is not None and before.video is not None
    assert after.video.nb_frames == before.video.nb_frames
    assert _audio_md5(video) == sound
    assert fit.av_error_s is None or abs(fit.av_error_s) <= 0.02


def test_a_video_already_under_the_limit_is_left_alone(tmp_path: Path) -> None:
    video = _heavy(tmp_path / "final.mp4", seconds=2)
    size = video.stat().st_size
    fit = fit_to_size(video, size + 1)
    assert not fit.reencoded and video.stat().st_size == size


def test_a_limit_too_small_for_the_length_is_refused(tmp_path: Path) -> None:
    video = _heavy(tmp_path / "final.mp4", seconds=4)
    with pytest.raises(ValidationError, match="Raise --max-size-mb"):
        fit_to_size(video, 150_000)


def test_the_bitrate_leaves_room_for_the_audio() -> None:
    # 45 s under 30 MB with 1 MB of AAC: about 4.8 Mbit/s for the picture.
    assert 4_700 < video_bitrate_for(30_000_000, 45.0, 1_000_000) < 5_000
