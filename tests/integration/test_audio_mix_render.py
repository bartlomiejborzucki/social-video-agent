"""The music bed and effects have to be audible in the file, not just in the graph."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from social_video.edl.render import render_edl
from social_video.ffmpeg.probe import probe
from social_video.schemas.edl import EDL, AudioBed, EDLRange, SoundEffect
from social_video.sources import build_manifest
from tests.conftest import ffmpeg, make_video, requires_ffmpeg


def _tone(path: Path, frequency: int, duration: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={frequency}:duration={duration}",
        "-c:a",
        "aac",
        str(path),
    )
    return path


def _band_share(path: Path, low: float, high: float, start: float = 0.0, end: float = 4.0) -> float:
    """Fraction of the spectrum's energy inside one band. Frequencies identify sources."""
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(start),
            "-t",
            str(end - start),
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    signal = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    spectrum = np.abs(np.fft.rfft(signal))
    freqs = np.fft.rfftfreq(len(signal), 1 / 48000)
    band = (freqs >= low) & (freqs <= high)
    return float(spectrum[band].sum() / max(1.0, spectrum.sum()))


@pytest.fixture
def media(tmp_path: Path) -> dict[str, Path]:
    # Distinct tones so each element can be identified in the output spectrum.
    talk = make_video(tmp_path / "talk.mp4", width=640, height=360, duration=6.0)
    return {
        "talk": talk,
        "bed": _tone(tmp_path / "bed.m4a", 880, 10.0),
        "short_bed": _tone(tmp_path / "short.m4a", 880, 1.0),
        "ping": _tone(tmp_path / "ping.m4a", 1500, 0.4),
    }


def _edl(source_id: str, **kwargs) -> EDL:
    return EDL(
        name="mix",
        output_width=1080,
        output_height=1920,
        ranges=[EDLRange(source=source_id, start=0.0, end=4.0)],
        **kwargs,
    )


@pytest.mark.integration
@pytest.mark.slow
@requires_ffmpeg
def test_the_bed_and_the_effect_are_present_in_the_rendered_audio(
    tmp_path: Path, media: dict[str, Path]
) -> None:
    manifest = build_manifest([media["talk"]])
    source_id = manifest.ids[0]
    plain = render_edl(_edl(source_id), manifest, tmp_path / "plain.mp4")
    assert plain.audio_bed_applied == {}

    mixed = render_edl(
        _edl(
            source_id,
            audio_bed=AudioBed(
                path=str(media["bed"]),
                gain_db=-20.0,
                reason="Podkład pod część techniczną.",
                license_confirmed=True,
            ),
            sound_effects=[
                SoundEffect(
                    path=str(media["ping"]),
                    at=1.5,
                    reason="Akcent na liczbie.",
                    license_confirmed=True,
                )
            ],
        ),
        manifest,
        tmp_path / "mixed.mp4",
    )
    assert mixed.audio_bed_applied["ducked"] is True
    assert mixed.sound_effects_applied == 1

    # The mix must not change the edit: same length, same stream contract.
    assert abs(probe(tmp_path / "mixed.mp4").duration - 4.0) < 0.05

    bed_before = _band_share(tmp_path / "plain.mp4", 860, 900)
    bed_after = _band_share(tmp_path / "mixed.mp4", 860, 900)
    assert bed_after > bed_before * 5

    ping_before = _band_share(tmp_path / "plain.mp4", 1480, 1520, 1.3, 1.9)
    ping_after = _band_share(tmp_path / "mixed.mp4", 1480, 1520, 1.3, 1.9)
    assert ping_after > ping_before * 10


@pytest.mark.integration
@pytest.mark.slow
@requires_ffmpeg
def test_ducking_pulls_the_bed_down_under_speech(tmp_path: Path, media: dict[str, Path]) -> None:
    manifest = build_manifest([media["talk"]])
    source_id = manifest.ids[0]

    def render(duck: bool, name: str) -> Path:
        bed = AudioBed(
            path=str(media["bed"]),
            gain_db=-20.0,
            duck=duck,
            reason="Podkład.",
            license_confirmed=True,
        )
        render_edl(_edl(source_id, audio_bed=bed), manifest, tmp_path / f"{name}.mp4")
        return tmp_path / f"{name}.mp4"

    ducked = _band_share(render(True, "ducked"), 860, 900)
    flat = _band_share(render(False, "flat"), 860, 900)
    assert flat > ducked * 1.3


@pytest.mark.integration
@requires_ffmpeg
def test_a_bed_too_short_for_the_edit_is_refused_unless_looping_is_declared(
    tmp_path: Path, media: dict[str, Path]
) -> None:
    manifest = build_manifest([media["talk"]])
    source_id = manifest.ids[0]
    bed = AudioBed(path=str(media["short_bed"]), reason="Za krótki.", license_confirmed=True)
    with pytest.raises(ValueError, match="loop: true"):
        render_edl(_edl(source_id, audio_bed=bed), manifest, tmp_path / "short.mp4")

    looped = bed.model_copy(update={"loop": True})
    manifest_out = render_edl(_edl(source_id, audio_bed=looped), manifest, tmp_path / "looped.mp4")
    assert manifest_out.audio_bed_applied["looped"] is True
