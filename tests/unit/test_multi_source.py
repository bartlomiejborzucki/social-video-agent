"""2.3: an edit cut from several recordings, without hand-written scripts."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from social_video.captions.chunk import build_caption_track
from social_video.captions.fix import carry_fixes, fix_words
from social_video.cli import app
from social_video.editorial.compile import compile_plan
from social_video.edl.timeline import Timeline
from social_video.errors import ValidationError
from social_video.motion.layout import pin_labels
from social_video.pipeline import plan_transcripts
from social_video.profiles import load_profile
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionFixRecord, CaptionTrack, CaptionWord
from social_video.schemas.edl import EDL, EDLRange, ReframeMode, ReframePlan, SoundEffect
from social_video.schemas.motion import MotionElement, MotionElementType
from social_video.schemas.plan import EditPlan, PlanAction, PlanItem
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing
from social_video.workspace.layout import Workspace
from tests.conftest import make_video, requires_ffmpeg

PROFILE = load_profile("talking-head")


def _transcript(source: str, words: list[tuple[str, float, float]], duration: float = 30.0):
    tokens = [TranscriptToken(type=TokenType.WORD, text=t, start=s, end=e) for t, s, e in words]
    return Transcript(
        source_id=source, source_fingerprint=source, duration=duration, provider="test",
        tokens=synthesize_spacing(tokens),
    )  # fmt: skip


#: The 13.10 reel: a child's voice on its own file, then three takes of the mother.
CHILD = _transcript("dziecko", [("Mamo,", 0.5, 0.9), ("pobaw", 0.95, 1.3), ("się!", 1.35, 1.8)])
KUBEK = _transcript("kubek", [("Mhm.", 4.0, 4.4)])
ODRUCH = _transcript(
    "odruch", [("Teraz", 2.0, 2.4), ("pobaw", 2.5, 2.9), ("się", 3.0, 3.2), ("sam.", 3.3, 3.8)]
)
SPROBUJ = _transcript(
    "sprobuj", [("Nie", 1.0, 1.2), ("pobawię", 1.3, 1.9), ("się", 2.0, 2.2), ("teraz.", 2.3, 2.9)]
)


def _keep(source: str, start: float, end: float, order: int, **fields) -> PlanItem:
    return PlanItem(action=PlanAction.KEEP, source=source, start=start, end=end, order=order,
                    reason=f"{source} scene", **fields)  # fmt: skip


def _plan() -> EditPlan:
    return EditPlan(
        goal="Granica bez kary",
        items=[
            _keep("sprobuj", 0.9, 3.0, order=3, beat="Spróbuj tak"),
            _keep("kubek", 0.0, 3.0, order=1, audio_source="dziecko", audio_start=0.4,
                  audio_end=1.9, reframe=ReframePlan(mode=ReframeMode.MANUAL, crop_width=1080,
                  crop_height=1920, keyframes=[{"t": 0, "x": 420, "y": 0}], reason="Twarz.")),
            _keep("odruch", 1.9, 3.9, order=2, beat="Częsty odruch"),
        ],
    )  # fmt: skip


def _edl() -> EDL:
    others = {"dziecko": CHILD, "odruch": ODRUCH, "sprobuj": SPROBUJ}
    return compile_plan(_plan(), KUBEK, PROFILE, transcripts=others)


def test_a_plan_cut_from_four_recordings_compiles_in_order() -> None:
    edl = _edl()

    assert [r.source for r in edl.ranges] == ["kubek", "odruch", "sprobuj"]
    first = edl.ranges[0]
    assert first.audio_source == "dziecko", "the child's voice under the mug shot"
    assert first.audio_start <= 0.5 and first.audio_end >= 1.8
    assert first.end - first.start == pytest.approx(first.audio_end - first.audio_start)
    assert first.reframe is not None and first.reframe.keyframes[0].x == 420
    assert [r.beat for r in edl.ranges] == ["", "Częsty odruch", "Spróbuj tak"]
    assert edl.ranges[1].start <= 2.0 and edl.ranges[1].end >= 3.8, "snapped to the words"


def test_a_voice_longer_than_its_picture_is_refused_with_the_fix() -> None:
    plan = EditPlan(
        goal="g",
        items=[_keep("kubek", 0.0, 0.5, order=1, audio_source="dziecko", audio_start=0.4,
                     audio_end=1.9)],
    )  # fmt: skip
    with pytest.raises(ValueError, match="extend end to at least"):
        compile_plan(plan, KUBEK, PROFILE, transcripts={"dziecko": CHILD})


def test_a_plan_item_names_its_voice_whole() -> None:
    with pytest.raises(ValueError, match="set together"):
        PlanItem(action="keep", source="a", start=0, end=1, audio_source="b")


def test_compile_needs_every_transcript_it_keeps_words_from(tmp_path: Path) -> None:
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    save_artifact(ODRUCH, ws.transcript_for("odruch"))
    with pytest.raises(ValidationError, match=r"'dziecko'.*no transcript"):
        plan_transcripts(_plan(), ws, primary="kubek")
    save_artifact(CHILD, ws.transcript_for("dziecko"))
    save_artifact(SPROBUJ, ws.transcripts / "sprobuj.track1.json")
    assert set(plan_transcripts(_plan(), ws, primary="kubek")) == {"dziecko", "odruch", "sprobuj"}


def test_captions_from_several_transcripts_are_one_numbered_track() -> None:
    edl = _edl()
    track = build_caption_track(
        [KUBEK, CHILD, ODRUCH, SPROBUJ], Timeline(edl), style=CaptionStyle(max_words_per_cue=4)
    )

    text = " ".join(c.text for c in track.cues)
    assert text.startswith("Mamo, pobaw się!")
    assert "Teraz pobaw się sam." in text and "Nie pobawię się teraz." in text
    assert "Mhm." not in text, "the mug take's own sound is not in the edit"
    assert [c.index for c in track.cues] == list(range(1, len(track.cues) + 1))
    assert track.overlapping() == []


def test_hold_through_pauses_fills_the_scene_but_not_across_a_cut() -> None:
    edl = EDL(ranges=[EDLRange(source="odruch", start=1.9, end=3.9),
                      EDLRange(source="sprobuj", start=0.9, end=3.0)])  # fmt: skip
    plain = build_caption_track(
        [ODRUCH, SPROBUJ], Timeline(edl), style=CaptionStyle(max_words_per_cue=2)
    )
    held = build_caption_track(
        [ODRUCH, SPROBUJ], Timeline(edl),
        style=CaptionStyle(max_words_per_cue=2, hold_through_pauses=True),
    )  # fmt: skip
    cut = Timeline(edl).cut_boundaries()[0]
    gaps = [b.start - a.end for a, b in zip(plain.cues, plain.cues[1:], strict=False)]
    assert any(g > 0.05 for g in gaps), "the fixture has pauses to hold through"
    for a, b in zip(held.cues, held.cues[1:], strict=False):
        if a.start < cut <= b.start:
            assert b.start - a.end > 0.05 or a.end <= cut, "a cut still clears the screen"
        else:
            assert b.start - a.end == pytest.approx(0.01, abs=0.002)


def test_labels_are_pinned_to_the_scenes_the_edit_made() -> None:
    edl = _edl()
    timeline = Timeline(edl)
    brief_times = [
        MotionElement(type=MotionElementType.LABEL, start=3.0, end=9.0, text="Częsty odruch",
                      reason="brief"),
        MotionElement(type=MotionElementType.LABEL, start=9.0, end=22.0, text="Spróbuj tak",
                      reason="brief"),
    ]  # fmt: skip

    pinned, notes = pin_labels(brief_times, edl)

    odruch, sprobuj = timeline.slices[1], timeline.slices[2]
    assert pinned[0].start == pytest.approx(odruch.output_start, abs=1e-3)
    assert pinned[0].end == pytest.approx(sprobuj.output_start, abs=1e-3), "the scenes meet"
    assert pinned[1].end == pytest.approx(timeline.duration, abs=1e-3)
    assert len(notes) == 2 and "beat 'Częsty odruch'" in notes[0]


def _track() -> CaptionTrack:
    words = [CaptionWord(text="pobaw", start=6.0, end=6.4), CaptionWord(text="się", start=6.5,
             end=6.7), CaptionWord(text="sam.", start=6.8, end=7.2)]  # fmt: skip
    return CaptionTrack(
        cues=[CaptionCue(index=1, start=6.0, end=7.2, text="pobaw się sam.", words=words)]
    )


def test_a_caption_fix_changes_the_words_the_highlight_draws() -> None:
    fixed, change = fix_words(_track(), at=6.9, old="sam.", new="już.")
    cue = fixed.cues[0]
    assert cue.text == "pobaw się już." and change.before == "pobaw się sam."
    assert [w.text for w in cue.words] == ["pobaw", "się", "już."]
    assert (cue.words[-1].start, cue.words[-1].end) == (6.8, 7.2), "timing kept"
    assert fixed.corrected

    two, _ = fix_words(_track(), at=6.1, old="Pobaw się", new="baw się teraz")
    assert [w.text for w in two.cues[0].words][:3] == ["baw", "się", "teraz"]
    with pytest.raises(ValidationError, match="has no 'potem'"):
        fix_words(_track(), at=6.9, old="potem", new="już")
    with pytest.raises(ValidationError, match=r"no caption on screen at 20\.00s"):
        fix_words(_track(), at=20.0, old="sam.", new="już.")


def test_a_rebuilt_track_gets_its_fixes_back_or_names_them() -> None:
    fixed, _ = fix_words(_track(), at=6.9, old="sam.", new="już.")
    assert fixed.fixes == [CaptionFixRecord(at=6.6, old="sam.", new="już.")]

    # The edit moved the cue 2 s later: the one cue with the old words takes it.
    moved = _track().model_copy(update={"cues": [_track().cues[0].model_copy(update={
        "start": 8.0, "end": 9.2,
        "words": [w.model_copy(update={"start": w.start + 2, "end": w.end + 2})
                  for w in _track().cues[0].words]})]})  # fmt: skip
    carried, lost = carry_fixes(moved, fixed.fixes)
    assert carried.cues[0].text == "pobaw się już." and lost == []
    assert carried.fixes[0].at == pytest.approx(8.6)

    # The transcript was corrected meanwhile: nothing left to do, the fix is kept.
    done, lost = carry_fixes(carried.model_copy(update={"fixes": []}), fixed.fixes)
    assert done.cues[0].text == "pobaw się już." and lost == [] and done.fixes == fixed.fixes

    # The words are cut out of the edit: the fix is named, not dropped silently.
    mamo = CaptionWord(text="Mamo,", start=0, end=1)
    cut = CaptionTrack(cues=[CaptionCue(index=1, start=0, end=1, text="Mamo,", words=[mamo])])
    _same, lost = carry_fixes(cut, fixed.fixes)
    assert lost == fixed.fixes


def test_the_cli_rewrites_every_caption_file(tmp_path: Path) -> None:
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    base = ws.captions / "main.ass"
    save_artifact(_track(), base.with_suffix(".json"))
    save_artifact(EDL(ranges=[EDLRange(source="a", start=0, end=8)], captions=str(base)), ws.edl)

    result = CliRunner().invoke(
        app, ["captions", "fix", "-w", str(ws.root), "--at", "6.9", "--from", "sam.", "--to",
              "już."],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert load_artifact(CaptionTrack, base.with_suffix(".json")).cues[0].text.endswith("już.")
    for suffix in (".srt", ".vtt", ".ass"):
        assert "już." in base.with_suffix(suffix).read_text(encoding="utf-8")


def _voice_only_workspace(tmp_path: Path) -> tuple[Workspace, Path]:
    """A picture-only playground clip whose voice is a separate, transcribed file."""
    from social_video.pipeline import stage_ingest

    picture = make_video(tmp_path / "plener.mp4", duration=3.0, audio=False)
    ws = Workspace.at(tmp_path / "edit")
    stage_ingest(picture, ws)
    save_artifact(CHILD.model_copy(update={"source_id": "glos"}), ws.transcript_for("glos"))
    save_artifact(
        EditPlan(
            goal="voice over the playground",
            items=[
                _keep(
                    "plener",
                    0.0,
                    2.5,
                    order=1,
                    audio_source="glos",
                    audio_start=0.4,
                    audio_end=1.9,
                ),
            ],
        ),
        ws.edit_plan,
    )
    return ws, picture


@requires_ffmpeg
@pytest.mark.parametrize("with_source", [False, True])
def test_compile_needs_no_sound_on_the_primary(tmp_path: Path, with_source: bool) -> None:
    ws, picture = _voice_only_workspace(tmp_path)
    args = ["compile", "-w", str(ws.root), "--no-captions", "--word-edges"]
    if with_source:
        args.insert(1, str(picture))
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    edl = load_artifact(EDL, ws.edl)
    assert edl.ranges[0].source == "plener"
    assert edl.ranges[0].audio_source == "glos"


def test_compile_without_any_transcribed_sound_says_what_is_missing(tmp_path: Path) -> None:
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    save_artifact(EditPlan(goal="x", items=[_keep("plener", 0.0, 2.0, order=1)]), ws.edit_plan)
    result = CliRunner().invoke(app, ["compile", "-w", str(ws.root), "--no-captions"])
    assert result.exit_code == 1
    assert "no transcript in" in result.output


def test_zoom_speed_and_grade_on_a_plan_item_survive_compile() -> None:
    plan = EditPlan(
        goal="sharp jump",
        items=[
            _keep("odruch", 1.9, 3.9, order=1),
            _keep("sprobuj", 0.9, 3.0, order=2, zoom=1.1, grade="mono"),
        ],
    )
    edl = compile_plan(plan, ODRUCH, PROFILE, transcripts={"sprobuj": SPROBUJ})
    assert [(r.zoom, r.grade) for r in edl.ranges] == [(1.0, ""), (1.1, "mono")]


def test_a_recompile_names_the_editorial_fixes_it_dropped() -> None:
    from social_video.editorial.review import lost_editorial_fixes
    from social_video.schemas.editorial_qa import EditorialQA

    review = EditorialQA.model_validate(
        {
            "status": "changes_requested",
            "fixes": [
                {"artifact": "edl", "path": "ranges[1].zoom", "value": 1.1},
                {"artifact": "edl", "path": "ranges[7].zoom", "value": 1.1},
            ],
        }
    )
    plan = EditPlan(
        goal="x", items=[_keep("odruch", 1.9, 3.9, order=1), _keep("sprobuj", 0.9, 3.0, order=2)]
    )
    edl = compile_plan(plan, ODRUCH, PROFILE, transcripts={"sprobuj": SPROBUJ})
    lost = lost_editorial_fixes(edl, review)
    assert len(lost) == 2
    assert "set zoom on its edit-plan.json item" in lost[0]
    assert "no longer exists" in lost[1]
    plan.items[1].zoom = 1.1
    edl = compile_plan(plan, ODRUCH, PROFILE, transcripts={"sprobuj": SPROBUJ})
    assert len(lost_editorial_fixes(edl, review)) == 1


def test_a_slowed_picture_keeps_the_voice_at_its_own_pace() -> None:
    plan = EditPlan(
        goal="playground under the child's voice",
        items=[
            _keep("plac", 0.0, 1.5, order=1, audio_source="dziecko", audio_start=0.45,
                  audio_end=1.85, speed=0.88),
        ],
    )  # fmt: skip
    edl = compile_plan(plan, CHILD, PROFILE, source_id="plac", transcripts={"dziecko": CHILD})
    rng = edl.ranges[0]
    voice = rng.audio_end - rng.audio_start
    assert rng.voice_speed == 1.0
    assert rng.end == pytest.approx(voice * 0.88, abs=1e-3)
    assert rng.output_duration == pytest.approx(voice, abs=1e-3)
    timeline = Timeline(edl)
    assert timeline.slices[0].to_output(rng.audio_start + 1.0) == pytest.approx(1.0)


def test_a_voice_longer_than_the_slowed_picture_says_which_speed_fits() -> None:
    plan = EditPlan(
        goal="x",
        items=[
            _keep("plac", 0.0, 1.0, order=1, audio_source="dziecko", audio_start=0.45,
                  audio_end=1.85),
        ],
    )  # fmt: skip
    with pytest.raises(ValueError, match=r"set speed to 0\.\d+ or less"):
        compile_plan(plan, CHILD, PROFILE, source_id="plac", transcripts={"dziecko": CHILD})


@requires_ffmpeg
def test_a_forced_compile_says_it_dropped_the_sound_effects(tmp_path: Path) -> None:
    ws, _ = _voice_only_workspace(tmp_path)
    args = ["compile", "-w", str(ws.root), "--no-captions", "--word-edges"]
    assert CliRunner().invoke(app, args).exit_code == 0
    edl = load_artifact(EDL, ws.edl)
    effect = SoundEffect(path="pop.wav", at=0.5, reason="a pop under the label")
    save_artifact(edl.model_copy(update={"sound_effects": [effect]}), ws.edl)

    result = CliRunner().invoke(app, [*args, "--force"])

    assert result.exit_code == 0, result.output
    assert "had 1 sound effect(s)" in " ".join(result.output.split())


@requires_ffmpeg
def test_a_forced_compile_keeps_the_caption_fixes(tmp_path: Path) -> None:
    ws, _ = _voice_only_workspace(tmp_path)
    args = ["compile", "-w", str(ws.root), "--captions", "--word-edges"]
    assert CliRunner().invoke(app, args).exit_code == 0, "first compile"
    fix = ["captions", "fix", "-w", str(ws.root), "--at", "0.8"]
    assert CliRunner().invoke(app, [*fix, "--from", "pobaw", "--to", "baw"]).exit_code == 0
    track = ws.captions / "main.json"
    assert load_artifact(CaptionTrack, track).fixes != []
    # A fix the next compile cannot place: its words are not said.
    data = load_artifact(CaptionTrack, track)
    gone = CaptionFixRecord(at=0.5, old="kubek", new="kubeczek")
    save_artifact(data.model_copy(update={"fixes": [*data.fixes, gone]}), track)

    result = CliRunner().invoke(app, [*args, "--force"])

    assert result.exit_code == 0, result.output
    rebuilt = load_artifact(CaptionTrack, track)
    assert "baw" in [w.text for c in rebuilt.cues for w in c.words]
    assert "baw" in (ws.captions / "main.srt").read_text(encoding="utf-8")
    out = " ".join(result.output.split())
    assert "captions fix 'kubek' -> 'kubeczek' (at 0.50s) is not in the rebuilt captions" in out
    assert "'pobaw' -> 'baw'" not in out
