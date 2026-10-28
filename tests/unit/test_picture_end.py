"""A phone recording whose picture stops before its sound."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from social_video.cli import app
from social_video.editorial.compile import fit_to_picture
from social_video.edl.render import render_edl
from social_video.ffmpeg.probe import probe
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.edl import EDL, EDLRange, VisualFillStrategy
from social_video.schemas.plan import EditPlan, PlanAction, PlanItem
from social_video.schemas.source import SourceManifest
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing
from social_video.workspace.layout import Workspace
from tests.conftest import ffmpeg, requires_ffmpeg


def test_a_range_a_little_past_the_picture_holds_its_last_frame() -> None:
    edl = EDL(ranges=[EDLRange(source="telefon", start=1.0, end=5.6),
                      EDLRange(source="inne", start=0.0, end=2.0)])  # fmt: skip

    fitted, notes = fit_to_picture(edl, {"telefon": 5.2})

    held, other = fitted.ranges
    assert held.visual_fill_strategy is VisualFillStrategy.FREEZE
    assert (held.effective_video_end, held.freeze_at) == (5.2, 5.2)
    assert held.freeze_duration == pytest.approx(0.4)
    # The words stay whole, and so does the length of the edit.
    assert held.end == 5.6 and held.output_duration == pytest.approx(4.6)
    assert other == edl.ranges[1]
    assert notes == [
        "range 1.00-5.60s of 'telefon' runs 0.40s past the end of its picture (5.20s); "
        "the last frame is held 0.40s under the last words"
    ]
    assert fit_to_picture(fitted, {"telefon": 5.2}) == (fitted, [])


def test_a_range_far_past_the_picture_ends_with_it() -> None:
    edl = EDL(ranges=[EDLRange(source="telefon", start=1.0, end=7.0, speed=0.9)])

    fitted, notes = fit_to_picture(edl, {"telefon": 5.2})

    cut = fitted.ranges[0]
    assert cut.end == 5.2 and cut.visual_fill_strategy is None
    assert cut.output_duration == pytest.approx(4.2 / 0.9)
    assert "it now ends with the picture, and the words after it are cut" in notes[0]


def test_a_range_inside_its_picture_or_with_another_voice_is_left_alone() -> None:
    inside = EDL(ranges=[EDLRange(source="telefon", start=0.0, end=5.2)])
    assert fit_to_picture(inside, {"telefon": 5.2}) == (inside, [])
    voiced = EDL(ranges=[EDLRange(source="telefon", start=0.0, end=3.0, audio_source="glos",
                                  audio_start=0.0, audio_end=3.0)])  # fmt: skip
    assert fit_to_picture(voiced, {"telefon": 2.0})[1] == []


@requires_ffmpeg
def test_compile_and_render_keep_every_shot_in_place(tmp_path: Path) -> None:
    phone = tmp_path / "telefon.mp4"
    ffmpeg(
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=5.2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5.6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac",
        str(phone),
    )  # fmt: skip
    ws = Workspace.at(tmp_path / "edit")
    from social_video.pipeline import stage_ingest

    stage_ingest(phone, ws)
    source = load_artifact(SourceManifest, ws.source_manifest).ids[0]
    tokens = [TranscriptToken(type=TokenType.WORD, text=t, start=s, end=e)
              for t, s, e in [("Już", 4.4, 4.8), ("idziemy.", 4.9, 5.55)]]  # fmt: skip
    save_artifact(
        Transcript(source_id=source, source_fingerprint=source, duration=5.6, provider="test",
                   tokens=synthesize_spacing(tokens)),
        ws.transcript_for(source),
    )  # fmt: skip
    save_artifact(
        EditPlan(goal="g", items=[PlanItem(action=PlanAction.KEEP, source=source, start=4.2,
                                           end=5.6, order=1, reason="the last line")]),
        ws.edit_plan,
    )  # fmt: skip

    result = CliRunner().invoke(app, ["compile", "-w", str(ws.root), "--no-captions"])

    assert result.exit_code == 0, result.output
    assert "past the end of its picture (5.20s)" in " ".join(result.output.split())
    edl = load_artifact(EDL, ws.edl)
    assert edl.ranges[0].visual_fill_strategy is VisualFillStrategy.FREEZE
    manifest = load_artifact(SourceManifest, ws.source_manifest)
    out = tmp_path / "out.mp4"
    render_edl(edl, manifest, out)
    assert probe(out).duration == pytest.approx(edl.total_duration, abs=0.05)
