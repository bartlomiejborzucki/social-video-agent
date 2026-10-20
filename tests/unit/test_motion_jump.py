"""A cut inside one take, mid-sentence: a sharp framing jump, not a transition."""

from __future__ import annotations

from social_video.motion.energy import energy_preset
from social_video.motion.suggest import apply_range_zooms, find_accents
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import AccentKind
from social_video.schemas.plan import EditPlan, PlanAction, PlanItem
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing


def _transcript(words: list[tuple[str, float, float]]) -> Transcript:
    tokens = [TranscriptToken(type=TokenType.WORD, text=t, start=s, end=e) for t, s, e in words]
    return Transcript(
        source_id="kamera", source_fingerprint="x", duration=170.0, provider="test",
        tokens=synthesize_spacing(tokens),
    )  # fmt: skip


#: A take to the camera: "...trzeba też pomagać." | cut | "Potem o tym..."
KAMERA = _transcript(
    [("również", 152.6, 153.0), ("pomagać.", 153.05, 153.45), ("z", 153.6, 153.7),
     ("Potem", 156.85, 157.2), ("o", 157.25, 157.3), ("tym", 157.35, 157.6)]
)  # fmt: skip


def _edl(second_start: float) -> EDL:
    return EDL(
        ranges=[
            EDLRange(source="kamera", start=132.0, end=153.52),
            EDLRange(source="kamera", start=second_start, end=163.7),
        ]
    )


def test_a_mid_speech_cut_in_one_take_gets_a_sharp_jump_not_a_transition() -> None:
    found = find_accents(KAMERA, _edl(156.82), energy_preset("bold"))
    at_cut = [c for c in found.candidates if abs(c.at - 21.52) < 0.01]
    assert [c.kind for c in at_cut] == [AccentKind.JUMP]
    move = at_cut[0].range_zoom
    assert move is not None and move.range_index == 1 and 1.08 <= move.zoom <= 1.12


def test_a_cut_into_a_pause_may_still_get_a_transition() -> None:
    found = find_accents(KAMERA, _edl(156.0), energy_preset("bold"))
    kinds = {c.kind for c in found.candidates if abs(c.at - 21.52) < 0.01}
    assert AccentKind.JUMP not in kinds


def test_accepting_a_jump_sets_the_zoom_on_the_plan_item_and_the_range() -> None:
    plan = EditPlan(
        goal="x",
        items=[
            PlanItem(action=PlanAction.KEEP, source="kamera", start=132.0, end=153.53, order=1),
            PlanItem(action=PlanAction.KEEP, source="kamera", start=156.85, end=163.75, order=2),
        ],
    )
    found = find_accents(KAMERA, _edl(156.82), energy_preset("bold"))
    jump = [c for c in found.candidates if c.range_zoom is not None]
    edl, updated, notes = apply_range_zooms(_edl(156.82), plan, jump)
    assert [r.zoom for r in edl.ranges] == [1.0, 1.1]
    assert updated is not None and [i.zoom for i in updated.items] == [1.0, 1.1]
    assert "on plan item 1" in notes[0]
