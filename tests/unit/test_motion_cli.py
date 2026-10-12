"""The `motion` and `broll` commands end to end, without models or a renderer."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from social_video.cli import app
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionPlan, Transition
from social_video.schemas.transcript import Transcript, TranscriptToken
from social_video.schemas.workflow import Renderer
from social_video.transcribe.normalize import synthesize_spacing
from social_video.workspace.layout import Workspace
from tests.conftest import make_video, requires_ffmpeg

SPEECH = [
    ("Trzy", 0.0, 0.3), ("błędy", 0.35, 0.7), ("zabijają", 0.75, 1.2), ("zasięgi.", 1.25, 1.8),
    ("Aż", 3.0, 3.2), ("73", 3.25, 3.5), ("procent", 3.55, 3.9), ("ogląda", 3.95, 4.3),
    ("bez", 4.35, 4.5), ("dźwięku.", 4.55, 5.0),
    ("Po", 7.0, 7.1), ("pierwsze", 7.15, 7.5), ("napisy,", 7.55, 7.9), ("po", 8.0, 8.1),
    ("drugie", 8.15, 8.5), ("hook.", 8.55, 8.9),
    ("Ale", 11.0, 11.2), ("to", 11.25, 11.3), ("nie", 11.35, 11.5), ("wszystko.", 11.55, 12.0),
]  # fmt: skip

runner = CliRunner()


def _transcript() -> Transcript:
    tokens = [TranscriptToken(text=t, start=s, end=e) for t, s, e in SPEECH]
    return Transcript(
        source_id="clip",
        source_fingerprint="f" * 16,
        duration=14.0,
        provider="test",
        tokens=synthesize_spacing(tokens),
    )


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    transcript = _transcript()
    monkeypatch.setattr("social_video.pipeline.stage_transcribe", lambda *a, **k: transcript)
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    save_artifact(
        EDL(
            ranges=[
                EDLRange(source="clip", start=0, end=9.5),
                EDLRange(source="clip", start=10.8, end=14.0),
            ]
        ),
        ws.edl,
    )
    return ws


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "broll"
    folder.mkdir()
    (folder / "napisy.mp4").write_bytes(b"x")
    (folder / "ekran.mov").write_bytes(b"x")
    (folder / "ekran.mov.txt").write_text("zasięgi, wykres", encoding="utf-8")
    (folder / "notes.txt").write_text("not a clip", encoding="utf-8")
    monkeypatch.setattr(
        "social_video.ffmpeg.probe.probe", lambda path: SimpleNamespace(duration=5.0)
    )
    return folder


def _invoke(*args: str):
    return runner.invoke(app, list(args))


# -- broll ---------------------------------------------------------------------


def test_broll_suggest_finds_clips_by_name_and_sidecar_tags(
    workspace: Workspace, library: Path
) -> None:
    result = _invoke("broll", "suggest", "clip.mp4", "--library", str(library),
                     "-w", str(workspace.root))  # fmt: skip

    assert result.exit_code == 0, result.output
    from social_video.motion.broll import BrollCandidateSet

    found = load_artifact(BrollCandidateSet, workspace.broll_candidates)
    by_file = {Path(c.file).name: c for c in found.candidates}
    assert set(by_file) == {"napisy.mp4", "ekran.mov"}
    assert by_file["ekran.mov"].keyword == "zasięgi"
    assert by_file["ekran.mov"].at == pytest.approx(1.25)
    assert by_file["napisy.mp4"].at == pytest.approx(7.55)
    assert all(c.confidence == "high" for c in found.candidates)
    assert all(c.duration == pytest.approx(3.5) for c in found.candidates)  # MAX_SHOT
    assert [c.id for c in found.candidates] == ["br-001", "br-002"]


def test_broll_accept_adds_overlays_once_and_names_unknown_ids(
    workspace: Workspace, library: Path
) -> None:
    ws = str(workspace.root)
    _invoke("broll", "suggest", "clip.mp4", "--library", str(library), "-w", ws)

    first = _invoke("broll", "accept", "br-002", "br-002", "-w", ws)
    again = _invoke("broll", "accept", "br-002", "-w", ws)
    unknown = _invoke("broll", "accept", "br-999", "-w", ws)

    assert first.exit_code == 0, first.output
    assert again.exit_code == 0, again.output
    overlays = load_artifact(EDL, workspace.edl).overlays
    assert len(overlays) == 1
    assert Path(overlays[0].file).name == "napisy.mp4"
    assert overlays[0].start_in_output == pytest.approx(7.55)
    assert unknown.exit_code == 1
    assert "unknown b-roll candidate 'br-999'" in unknown.output


def test_broll_suggest_refuses_without_an_edl_or_a_library(
    tmp_path: Path, workspace: Workspace, library: Path
) -> None:
    missing_library = _invoke("broll", "suggest", "clip.mp4", "--library",
                              str(tmp_path / "nowhere"), "-w", str(workspace.root))  # fmt: skip
    workspace.edl.unlink()
    missing_edl = _invoke("broll", "suggest", "clip.mp4", "--library", str(library),
                          "-w", str(workspace.root))  # fmt: skip

    assert missing_library.exit_code == 1 and "no b-roll library" in missing_library.output
    assert missing_edl.exit_code == 1 and "no EDL" in missing_edl.output


# -- motion --------------------------------------------------------------------


def test_motion_accept_needs_suggestions_first(workspace: Workspace) -> None:
    result = _invoke("motion", "accept", "acc-001", "-w", str(workspace.root))

    assert result.exit_code == 1
    assert "run `motion suggest`" in result.output
    assert not workspace.motion_plan.exists()


def test_motion_accept_filters_by_kind_and_confidence(workspace: Workspace) -> None:
    ws = str(workspace.root)
    assert _invoke("motion", "suggest", "clip.mp4", "-w", ws, "--energy", "bold").exit_code == 0

    nothing = _invoke("motion", "accept", "-w", ws, "--kind", "question")
    medium_only = _invoke("motion", "accept", "-w", ws, "--kind", "steps",
                          "--confidence", "high", "--json")  # fmt: skip

    assert nothing.exit_code == 0 and "No accents of that kind." in nothing.output
    assert medium_only.exit_code == 0 and '"elements": 0' in medium_only.output
    assert not workspace.motion_plan.exists()

    hook = _invoke("motion", "accept", "-w", ws, "--kind", "hook", "--json")

    assert hook.exit_code == 0, hook.output
    plan = load_artifact(MotionPlan, workspace.motion_plan)
    assert [e.type.value for e in plan.elements] == ["hook_card"]


def test_motion_suggest_json_reports_the_energy_used(workspace: Workspace) -> None:
    result = _invoke("motion", "suggest", "clip.mp4", "-w", str(workspace.root),
                     "--energy", "calm", "--json")  # fmt: skip

    assert result.exit_code == 0, result.output
    assert '"energy": "calm"' in result.output
    assert '"transition"' not in result.output


def test_motion_variants_refuse_the_ffmpeg_renderer(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "social_video.workflow.load_workflow",
        lambda ws: SimpleNamespace(renderer=Renderer.FFMPEG),
    )

    result = _invoke("motion", "variants", "--text", "A", "--text", "B",
                     "-w", str(workspace.root))  # fmt: skip

    assert result.exit_code == 1
    assert "drawn by Remotion" in result.output
    assert not list(workspace.previews.glob("hook-*.mp4"))


@requires_ffmpeg
def test_motion_sheet_writes_one_tile_per_moment(tmp_path: Path, workspace: Workspace) -> None:
    video = make_video(tmp_path / "preview.mp4", duration=4.0)
    plan = MotionPlan(
        rationale="r",
        elements=[MotionElement(type="stat", start=1.0, end=2.0, text="73%", reason="r")],
        transitions=[Transition(at=3.0, reason="cut")],
    )
    save_artifact(plan, workspace.motion_plan)

    result = _invoke("motion", "sheet", "-w", str(workspace.root), "--video", str(video))

    assert result.exit_code == 0, result.output
    sheet = workspace.qa / "motion-sheet.png"
    from PIL import Image

    with Image.open(sheet) as image:
        assert image.width > 0 and image.height > 0


def test_motion_sheet_refuses_an_empty_plan(workspace: Workspace) -> None:
    save_artifact(MotionPlan(rationale="r"), workspace.motion_plan)

    result = _invoke("motion", "sheet", "-w", str(workspace.root), "--video", "none.mp4")

    assert result.exit_code == 1
    assert "nothing to review" in result.output
