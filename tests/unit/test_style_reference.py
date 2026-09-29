"""1.4: a reference video's rhythm, measured and mapped onto project settings."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from social_video.analysis.reference import (
    SHEET_FRAMES,
    analyze_reference,
    aspect_label,
    recommend,
    sheet_moments,
    shot_rhythm,
    speech_rhythm,
)
from social_video.analysis.silence import Pause
from social_video.schemas.base import load_artifact
from social_video.schemas.style_reference import StyleReference
from social_video.schemas.transcript import Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing
from tests.conftest import ffmpeg, requires_ffmpeg

HAS_SCENEDETECT = importlib.util.find_spec("scenedetect") is not None


def test_shot_rhythm_from_cuts():
    shots = shot_rhythm([1.0, 2.0, 4.0, 99.0], duration=6.0)
    assert shots.count == 4
    assert shots.median_seconds == 1.5
    assert shots.first_cut_seconds == 1.0
    assert shots.cuts_per_minute == 30.0


def test_single_shot():
    shots = shot_rhythm([], duration=20.0)
    assert shots.count == 1
    assert shots.first_cut_seconds is None
    rec = recommend(shots, None)
    assert rec.motion_energy == "calm"
    assert "scene detection cannot see" in rec.reasons[0]


def test_tight_talking_head_without_visible_cuts_reads_lively():
    speech = speech_rhythm([Pause(3.0, 3.4)], 30.0)
    assert speech.sound_ratio > 0.9
    assert recommend(shot_rhythm([], duration=30.0), speech).motion_energy == "lively"


@pytest.mark.parametrize(
    ("cuts", "energy"),
    [([1.0, 2.0, 3.0, 4.0], "bold"), ([3.0, 6.0, 9.0], "lively"), ([7.0, 14.0], "calm")],
)
def test_energy_follows_median_shot(cuts: list[float], energy: str):
    duration = cuts[-1] + (cuts[1] - cuts[0])
    assert recommend(shot_rhythm(cuts, duration), None).motion_energy == energy


def _transcript(texts: list[str]) -> Transcript:
    words = [
        TranscriptToken(text=text, start=0.5 + i * 0.3, end=0.5 + i * 0.3 + 0.25)
        for i, text in enumerate(texts)
    ]
    return Transcript(
        source_id="ref",
        source_fingerprint="f" * 16,
        duration=10.0,
        provider="fake",
        tokens=synthesize_spacing(words),
    )


def test_speech_pace_and_first_sentence():
    transcript = _transcript(["To", "działa.", "Serio", "działa", "świetnie!"])
    speech = speech_rhythm([], 10.0, transcript=transcript)
    assert speech.first_sentence_seconds == pytest.approx(1.05)
    assert speech.words_per_minute == pytest.approx(206.9)  # five words in 1.45 s
    rec = recommend(shot_rhythm([4.0], 10.0), speech)
    assert rec.hook_within_seconds == 1.5  # never promise a hook shorter than 1.5 s
    assert any("never speed up speech" in reason for reason in rec.reasons)


def test_aspect_labels():
    assert aspect_label(1080, 1920) == "9:16"
    assert aspect_label(1080, 1350) == "4:5"
    assert aspect_label(1920, 1080) == "16:9"
    assert aspect_label(1000, 700) == "10:7"


def test_contact_sheet_is_thinned_evenly():
    cuts = [float(i) for i in range(1, 40)]
    moments = sheet_moments(cuts, 40.0)
    assert len(moments) == SHEET_FRAMES
    assert moments[0][1].startswith("shot 1 ")
    assert moments[-1][1].startswith("shot 40 ")


def test_artifact_round_trips(tmp_path: Path):
    from social_video.schemas.base import save_artifact

    shots = shot_rhythm([2.0], 4.0)
    artifact = StyleReference(
        reference="ref.mp4",
        reference_fingerprint="abc",
        duration=4.0,
        width=1080,
        height=1920,
        fps=30.0,
        aspect_ratio="9:16",
        shots=shots,
        recommendation=recommend(shots, None),
    )
    path = save_artifact(artifact, tmp_path / "style-reference.json")
    assert load_artifact(StyleReference, path) == artifact


@requires_ffmpeg
@pytest.mark.skipif(not HAS_SCENEDETECT, reason="scenedetect not installed")
def test_cli_measures_a_cut_reference(tmp_path: Path):
    from typer.testing import CliRunner

    from social_video.cli import app

    reference = tmp_path / "ref.mp4"
    colours = ["red", "blue", "white", "green"]
    args: list[str] = []
    for colour in colours:
        args += ["-f", "lavfi", "-i", f"color=c={colour}:s=360x640:d=1.5:r=30"]
    ffmpeg(
        *args,
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-filter_complex", "[0][1][2][3]concat=n=4:v=1:a=0[v]",
        "-map", "[v]", "-map", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(reference),
    )  # fmt: skip
    before = reference.read_bytes()
    workspace = tmp_path / "edit"

    result = CliRunner().invoke(
        app, ["style", "analyze", str(reference), "-w", str(workspace), "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["shots"]["count"] == 4
    assert payload["aspect_ratio"] == "9:16"
    assert payload["recommendation"]["motion_energy"] == "bold"
    saved = load_artifact(StyleReference, workspace / "context" / "style-reference.json")
    assert Path(saved.contact_sheet or "").is_file()
    assert reference.read_bytes() == before


@requires_ffmpeg
def test_a_reference_without_video_is_refused(tmp_path: Path):
    from social_video.errors import ValidationError

    audio = tmp_path / "voice.m4a"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(audio))
    with pytest.raises(ValidationError, match="no video stream"):
        analyze_reference(audio)
