"""Measure and repair real audio, and prove a good recording is left alone.

The unit tests pin the decisions; these run the ffmpeg chain those decisions
produce and measure the result. A cleanup that is selected correctly but
implemented wrongly would pass the unit tests and fail here.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from social_video.edl.render import render_edl
from social_video.edl.voice import MAX_NOISE_REDUCTION_DB
from social_video.schemas.edl import EDL, EDLRange
from social_video.sources import build_manifest
from tests.conftest import ffmpeg, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

WINDOW = 4800


def _voice(path: Path, *, seconds: float = 6.0) -> Path:
    """A voice-like signal: band-limited noise with real pauses between words."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=240x426:rate=30:duration={seconds}",
        "-f",
        "lavfi",
        "-i",
        f"anoisesrc=color=pink:duration={seconds}:sample_rate=48000",
        "-filter_complex",
        "[1:a]highpass=f=90:poles=2,lowpass=f=3400,tremolo=f=0.7:d=1.0,volume=-16dB[a]",
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-ac",
        "2",
        "-shortest",
        str(path),
    )
    return path


def _degrade(clean: Path, path: Path, *, seconds: float = 6.0) -> Path:
    """The same voice over hiss, 50 Hz mains hum and 45 Hz rumble."""
    ffmpeg(
        "-i",
        str(clean),
        "-f",
        "lavfi",
        "-i",
        f"anoisesrc=color=white:duration={seconds}:sample_rate=48000",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=50:duration={seconds}:sample_rate=48000",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=45:duration={seconds}:sample_rate=48000",
        "-filter_complex",
        "[1:a]volume=-40dB[n];[2:a]volume=-32dB[h];[3:a]volume=-28dB[r];"
        "[0:a][n][h][r]amix=inputs=4:normalize=0[a]",
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-ac",
        "2",
        str(path),
    )
    return path


def _render(source: Path, output: Path, *, policy: str) -> dict:
    manifest = build_manifest([source])
    edl = EDL(
        output_width=240,
        output_height=426,
        output_fps="30/1",
        ranges=[EDLRange(source=manifest.ids[0], start=0, end=5)],
    )
    rendered = render_edl(edl, manifest, output, audio_cleanup_policy=policy)
    return {
        "policy": rendered.audio_cleanup_policy,
        **rendered.audio_cleanup_applied,
    }


def _band_db(path: Path, band: str = "") -> float:
    stderr = ffmpeg_capture(path, band)
    for line in stderr.splitlines():
        if "RMS level dB:" in line:
            return float(line.split(":")[-1])
    raise AssertionError(f"no RMS measurement for {path}")


def ffmpeg_capture(path: Path, band: str) -> str:
    import subprocess

    from social_video.ffmpeg.run import find_binary

    proc = subprocess.run(
        [
            find_binary("ffmpeg"),
            "-hide_banner",
            "-nostdin",
            "-i",
            str(path),
            "-af",
            f"{band}astats=measure_perchannel=none",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stderr


def _relative(path: Path, band: str) -> float:
    return _band_db(path, band) - _band_db(path)


LOW_BAND = "lowpass=f=60:poles=2,lowpass=f=60:poles=2,"
HUM_BAND = "bandpass=f=50:width_type=h:w=6,"


@pytest.mark.slow
def test_a_good_recording_is_rendered_untouched(tmp_path: Path) -> None:
    clean = _voice(tmp_path / "clean.mp4")

    evidence = _render(clean, tmp_path / "clean-out.mp4", policy="measured")

    assert evidence["changed"] is False
    assert evidence["chain"] == ""
    assert evidence["applied"] == []
    measured = evidence["measured"]
    assert measured["snr_db"] > 20, measured
    assert measured["clipped"] is False
    # Every decision is still recorded, so "nothing was needed" is evidence.
    assert {step["name"] for step in evidence["skipped"]} == {
        "rumble",
        "mains hum",
        "broadband noise",
        "sibilance",
        "dynamics",
        "clipping",
    }


@pytest.mark.slow
def test_a_noisy_recording_is_measurably_repaired(tmp_path: Path) -> None:
    clean = _voice(tmp_path / "clean.mp4")
    bad = _degrade(clean, tmp_path / "bad.mp4")
    before_rumble = _relative(bad, LOW_BAND)
    before_hum = _relative(bad, HUM_BAND)

    output = tmp_path / "bad-out.mp4"
    evidence = _render(bad, output, policy="measured")

    applied = {step["name"]: step for step in evidence["applied"]}
    assert "rumble" in applied
    assert "mains hum" in applied
    assert "broadband noise" in applied
    assert applied["broadband noise"]["noise_reduction_db"] <= MAX_NOISE_REDUCTION_DB
    assert applied["mains hum"]["fundamental_hz"] == 50
    # The chain did what it said: less low-frequency energy and less hum,
    # measured on the rendered file rather than taken from the plan.
    assert _relative(output, LOW_BAND) < before_rumble - 6
    assert _relative(output, HUM_BAND) < before_hum - 6
    assert math.isfinite(_band_db(output))


@pytest.mark.slow
def test_the_policy_and_the_flag_both_leave_the_audio_as_recorded(tmp_path: Path) -> None:
    clean = _voice(tmp_path / "clean.mp4")
    bad = _degrade(clean, tmp_path / "bad.mp4")

    off = _render(bad, tmp_path / "off.mp4", policy="none")

    assert off["policy"] == "none"
    assert off["changed"] is False
    assert off["measured"] == {}
    # Nothing was measured either: `none` must not even analyse the audio.
    assert off["applied"] == [] and off["skipped"] == []
