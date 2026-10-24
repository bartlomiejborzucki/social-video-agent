"""2.7: stills and a timed transcript for an editorial read of a reference, and its check."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from social_video.analysis.reference_editorial import (
    analysis_markdown,
    check_analysis,
    editorial_moments,
    with_material_limits,
)
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.reference_analysis import (
    FrameReason,
    Observation,
    ReferenceAnalysis,
    ReferenceFrame,
    ReferenceMaterial,
    ReferenceMeasures,
)
from tests.conftest import ffmpeg, requires_ffmpeg

HAS_SCENEDETECT = importlib.util.find_spec("scenedetect") is not None


def test_moments_cover_first_opening_cuts_and_last():
    moments = editorial_moments([2.0, 5.0], 8.0)
    reasons = {reason for _, reason in moments}
    assert moments[0] == (0.0, FrameReason.FIRST)
    assert moments[-1] == (7.75, FrameReason.LAST)
    assert [at for at, r in moments if r is FrameReason.OPENING] == [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
    assert (5.05, FrameReason.CUT) in moments
    assert FrameReason.SHOT_MIDDLE in reasons
    # The still at 2.05 s after the first cut is too close to the 2.0 s opening still.
    assert (2.05, FrameReason.CUT) not in moments
    times = [at for at, _ in moments]
    assert times == sorted(times)


def test_moments_are_thinned_but_keep_the_fixed_ones():
    cuts = [float(i) / 2 for i in range(1, 200)]
    moments = editorial_moments(cuts, 100.0, limit=12)
    assert len(moments) <= 12
    assert moments[0][1] is FrameReason.FIRST
    assert moments[-1][1] is FrameReason.LAST
    assert sum(r is FrameReason.OPENING for _, r in moments) == 6


def _material(duration: float = 10.0) -> ReferenceMaterial:
    return ReferenceMaterial(
        reference="ref.mp4",
        reference_fingerprint="abc",
        duration=duration,
        frames=[
            ReferenceFrame(id="f000", at=0.0, reason=FrameReason.FIRST, path="f000.jpg"),
            ReferenceFrame(id="f001", at=0.5, reason=FrameReason.OPENING, path="f001.jpg"),
        ],
        measures=ReferenceMeasures(first_cut_seconds=2.0),
        limitations=["2 stills from 10.0 s"],
    )


def _analysis(**changes) -> ReferenceAnalysis:
    section = {"not_found": "none"}
    data = {
        "reference_fingerprint": "abc",
        "opening_attention": {
            "observations": [
                {"id": "o1", "frame": "f000", "evidence": "frame", "text": "A hand holds a cup."},
                {
                    "id": "o2",
                    "at": 0.4,
                    "evidence": "transcript",
                    "text": "First words: a question.",
                },
            ],
            "hypotheses": [{"text": "The object makes the topic clear.", "based_on": ["o1"]}],
        },
        "said_vs_written": section,
        "promise": section,
        "development": section,
        "payoff": section,
        "ending": section,
        "transferable_pattern": "Open on the object in hand, then ask the question.",
    }
    data.update(changes)
    return ReferenceAnalysis.model_validate(data)


def test_a_sound_read_passes_and_states_the_material_limits():
    material = _material()
    analysis = _analysis()
    assert check_analysis(analysis, material) == []
    limited = with_material_limits(analysis, material)
    assert limited.limitations == ["2 stills from 10.0 s"]
    text = analysis_markdown(limited, material)
    assert "**o1** [f000, frame]" in text
    assert "*Hypothesis:* The object makes the topic clear. (based on o1)" in text
    assert "## Limitations" in text


def test_an_observation_needs_a_moment():
    with pytest.raises(ValueError, match="needs a time"):
        Observation(id="o9", evidence="frame", text="something")


def test_problems_are_reported():
    material = _material(duration=5.0)
    analysis = _analysis(
        reference_fingerprint="other",
        promise={
            "observations": [
                {"id": "o1", "at": 9.0, "evidence": "transcript", "text": "Duplicated id."},
                {"id": "o3", "frame": "f099", "evidence": "frame", "text": "Unknown still."},
            ],
            "hypotheses": [{"text": "Guess.", "based_on": ["o7"]}],
        },
        payoff={},
        needs_review=[{"start": 4.0, "end": 3.0, "reason": "gesture"}],
    )
    problems = "\n".join(check_analysis(analysis, material))
    assert "different reference file" in problems
    assert "o1 is used twice" in problems
    assert "past the end" in problems
    assert "frame f099" in problems
    assert "unknown observations o7" in problems
    assert "payoff: no observation" in problems
    assert "not inside the video" in problems


@requires_ffmpeg
@pytest.mark.skipif(not HAS_SCENEDETECT, reason="scenedetect not installed")
def test_cli_writes_stills_and_checks_a_read(tmp_path: Path):
    from typer.testing import CliRunner

    from social_video.cli import app

    reference = tmp_path / "ref.mp4"
    args: list[str] = []
    for colour in ["red", "blue", "white"]:
        args += ["-f", "lavfi", "-i", f"color=c={colour}:s=360x640:d=2:r=30"]
    ffmpeg(
        *args,
        "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
        str(reference),
    )  # fmt: skip
    before = reference.read_bytes()
    workspace = tmp_path / "edit"
    runner = CliRunner()

    result = runner.invoke(
        app, ["style", "analyze", str(reference), "-w", str(workspace), "--editorial", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    material = load_artifact(ReferenceMaterial, Path(payload["editorial"]["material"]))
    assert material.frames[0].reason is FrameReason.FIRST
    assert any(f.reason is FrameReason.CUT for f in material.frames)
    assert all(Path(f.path).is_file() for f in material.frames)
    assert any("not transcribed" in item for item in material.limitations)
    assert any("no audio stream" in item for item in material.limitations)
    assert reference.read_bytes() == before

    analysis = _analysis(reference_fingerprint=material.reference_fingerprint)
    save_artifact(analysis, workspace / "context" / "reference-analysis.json")
    checked = runner.invoke(app, ["style", "check-analysis", "-w", str(workspace), "--json"])
    assert checked.exit_code == 0, checked.output
    summary = workspace / "context" / "reference-analysis.md"
    assert "not transcribed" in summary.read_text(encoding="utf-8")

    bad = _analysis(reference_fingerprint="nope")
    path = save_artifact(bad, tmp_path / "bad.json")
    refused = runner.invoke(app, ["style", "check-analysis", str(path), "-w", str(workspace)])
    assert refused.exit_code == 1
