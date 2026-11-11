"""A seam the recording runs on across is rendered without a dip in the sound."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from social_video.edl.render import DRAFT, render_edl
from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import run_ffmpeg_bytes
from social_video.schemas.edl import CONTINUOUS, EDL, EDLRange
from social_video.sources import build_manifest
from tests.conftest import make_video, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

RATE = 48000


def _level_around(video: Path, at: float, half: float = 0.02) -> float:
    """RMS of the sound in the 40 ms centred on a moment."""
    raw = run_ffmpeg_bytes(
        ["-v", "error", "-i", str(video), "-map", "0:a:0", "-ac", "1", "-ar", str(RATE),
         "-f", "f32le", "-"],
        desc="decode the sound",
    )  # fmt: skip
    samples = np.frombuffer(raw, dtype=np.float32)
    low, high = int((at - half) * RATE), int((at + half) * RATE)
    return float(np.sqrt(np.mean(np.square(samples[low:high]))))


def _edl(transition: str) -> EDL:
    return EDL(
        output_width=360,
        output_height=640,
        output_fps="30",
        normalize_audio=False,
        ranges=[
            EDLRange(source="kamera", start=0.2, end=1.213),
            EDLRange(source="kamera", start=1.213, end=2.4, transition_in=transition),
        ],
    )


def test_the_sound_does_not_dip_where_the_recording_runs_on(tmp_path: Path) -> None:
    manifest = build_manifest([make_video(tmp_path / "kamera.mp4", duration=3.0)])
    render_edl(_edl("cut"), manifest, tmp_path / "cut.mp4", quality=DRAFT)
    render_edl(_edl(CONTINUOUS), manifest, tmp_path / "runs-on.mp4", quality=DRAFT)

    seam = round(1.013 * 30) / 30
    steady = _level_around(tmp_path / "runs-on.mp4", 0.5)
    assert _level_around(tmp_path / "cut.mp4", seam) < 0.8 * steady, "a cut fades at the splice"
    assert _level_around(tmp_path / "runs-on.mp4", seam) == pytest.approx(steady, rel=0.08)
    assert probe(tmp_path / "runs-on.mp4").duration == pytest.approx(
        probe(tmp_path / "cut.mp4").duration, abs=0.02
    )
