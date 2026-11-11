"""Two recordings at different levels come out of a render together."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from social_video.edl.render import DRAFT, render_edl
from social_video.ffmpeg.run import run_ffmpeg
from social_video.schemas.edl import EDL, EDLRange
from social_video.sources import build_manifest
from tests.conftest import ffmpeg, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _speaker(path: Path, volume_db: float, seconds: float = 5.0) -> Path:
    """A voice-like signal at a given level."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        "-f", "lavfi", "-i", f"testsrc=size=180x320:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:duration={seconds}:sample_rate=48000:seed=3",
        "-filter_complex",
        f"[1:a]highpass=f=120,lowpass=f=3400,tremolo=f=3:d=0.6,volume={volume_db}dB[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "ultrafast", "-c:a", "aac", "-b:a", "128k", str(path),
    )  # fmt: skip
    return path


def _loudness(video: Path, start: float, end: float) -> float:
    said = run_ffmpeg(
        ["-ss", f"{start}", "-to", f"{end}", "-i", str(video), "-af", "ebur128", "-f", "null",
         "-"],
        desc="measure a passage",
    )  # fmt: skip
    summary = said[said.rfind("Summary:") :]
    return float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))


def test_two_speakers_three_lu_apart_leave_the_render_together(tmp_path: Path) -> None:
    manifest = build_manifest(
        [_speaker(tmp_path / "gosc.mp4", -14.0), _speaker(tmp_path / "prowadzacy.mp4", -20.0)]
    )
    edl = EDL(
        output_width=180,
        output_height=320,
        ranges=[
            EDLRange(source="gosc", start=0.2, end=4.2),
            EDLRange(source="prowadzacy", start=0.2, end=4.2),
        ],
    )

    plain = render_edl(edl, manifest, tmp_path / "plain.mp4", quality=DRAFT)
    level = render_edl(
        edl, manifest, tmp_path / "level.mp4", quality=DRAFT, audio_cleanup_policy="measured"
    )

    def gap(name: str) -> float:
        video = tmp_path / name
        return abs(_loudness(video, 0.3, 3.7) - _loudness(video, 4.3, 7.7))

    assert gap("plain.mp4") > 4.0, "one gain over the whole mix keeps them apart"
    assert gap("level.mp4") < 1.5
    assert "levels" not in plain.audio_cleanup_applied
    levels = level.audio_cleanup_applied["levels"]
    assert set(levels["gain_db"]) == {"gosc", "prowadzacy"}
    assert levels["gain_db"]["gosc"] < 0 < levels["gain_db"]["prowadzacy"]
    assert any(s["name"] == "speech level" for s in level.audio_cleanup_applied["applied"])
    assert [r.audio_gain_db for r in edl.ranges] == [0.0, 0.0]
