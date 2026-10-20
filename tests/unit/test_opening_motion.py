"""The first shot starts where it moves; the hook word gets a push-in."""

from __future__ import annotations

from pathlib import Path

import pytest

from social_video.motion.energy import energy_preset
from social_video.motion.opening import opening_in_point
from social_video.motion.suggest import apply_range_starts, find_accents
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import AccentKind
from social_video.schemas.plan import EditPlan, PlanAction, PlanItem
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
from social_video.sources import build_manifest
from social_video.transcribe.normalize import synthesize_spacing
from tests.conftest import ffmpeg, requires_ffmpeg


def _transcript(sid: str, words: list[tuple[str, float, float]]) -> Transcript:
    tokens = [TranscriptToken(type=TokenType.WORD, text=t, start=s, end=e) for t, s, e in words]
    return Transcript(source_id=sid, source_fingerprint="x", duration=10.0, provider="test",
                      tokens=synthesize_spacing(tokens))  # fmt: skip


def _still_then_moving(path: Path) -> Path:
    # One second of a still frame, then the test pattern moving.
    ffmpeg(
        "-f", "lavfi", "-i", "color=c=gray:s=180x320:r=30:d=1",
        "-f", "lavfi", "-i", "testsrc2=s=180x320:r=30:d=4",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    )  # fmt: skip
    return path


@requires_ffmpeg
def test_a_still_opening_under_a_separate_voice_moves_to_the_movement(tmp_path: Path) -> None:
    plac = _still_then_moving(tmp_path / "plac.mp4")
    manifest = build_manifest([plac])
    edl = EDL(ranges=[EDLRange(source="plac", start=0.0, end=2.0, audio_source="glos",
                               audio_start=0.0, audio_end=2.0)])  # fmt: skip
    move = opening_in_point(edl, manifest, {})
    assert move is not None and 0.85 <= move.video_start <= 1.05
    plan = EditPlan(goal="g", items=[
        PlanItem(action=PlanAction.KEEP, source="plac", start=0.0, end=4.0, audio_source="glos",
                 audio_start=0.0, audio_end=2.0)])  # fmt: skip
    found = find_accents(_transcript("glos", [("Dziecko", 0.1, 0.5)]), edl,
                         energy_preset("bold"), opening=move)  # fmt: skip
    opening = [c for c in found.candidates if c.kind is AccentKind.OPENING]
    updated, new_plan, notes = apply_range_starts(edl, plan, opening)
    assert updated.ranges[0].start == pytest.approx(move.video_start)
    assert updated.ranges[0].end == pytest.approx(2.0 + move.video_start)
    assert new_plan is not None and new_plan.items[0].start == pytest.approx(move.video_start)
    assert "start at" in notes[0]


@requires_ffmpeg
def test_no_word_is_cut_to_open_on_movement(tmp_path: Path) -> None:
    plac = _still_then_moving(tmp_path / "plac.mp4")
    edl = EDL(ranges=[EDLRange(source="plac", start=0.0, end=3.0)])
    said = {"plac": _transcript("plac", [("Mamo", 0.2, 0.6)])}
    assert opening_in_point(edl, build_manifest([plac]), said) is None


def test_the_hook_punch_lands_on_the_first_key_word_after_one_second() -> None:
    words = [("Dziecko", 0.0, 0.5), ("miało", 0.55, 1.0), ("sprzątać", 1.05, 1.3),
             ("z", 1.3, 1.35), ("pokój", 1.4, 1.7)]  # fmt: skip
    transcript = _transcript("a", words)
    edl = EDL(ranges=[EDLRange(source="a", start=0.0, end=5.0)])
    found = find_accents(transcript, edl, energy_preset("bold"), hook_punch=True)
    punches = [c for c in found.candidates if c.kind is AccentKind.HOOK_PUNCH]
    assert len(punches) == 1 and punches[0].quote == "sprzątać"
    assert punches[0].punch_in is not None and punches[0].punch_in.scale == pytest.approx(1.16)
    calm = find_accents(transcript, edl, energy_preset("calm"), hook_punch=True)
    hook = [c for c in calm.candidates if c.kind is AccentKind.HOOK_PUNCH]
    assert hook and hook[0].punch_in is not None and hook[0].punch_in.scale == pytest.approx(1.12)
