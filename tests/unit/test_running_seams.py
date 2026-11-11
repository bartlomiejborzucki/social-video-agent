"""No cut where nothing is removed: passages that follow each other run on."""

from __future__ import annotations

from fractions import Fraction

import pytest

from social_video.editorial.compile import compile_plan, join_seams
from social_video.edl.render import align_running_seams, allocate_range_frames
from social_video.edl.timeline import Timeline
from social_video.ffmpeg.filters import audio_cut_fades
from social_video.motion.energy import energy_preset
from social_video.motion.suggest import find_accents
from social_video.profiles import load_profile
from social_video.schemas.edl import CONTINUOUS, EDL, PUNCH, EDLRange
from social_video.schemas.motion import AccentKind
from social_video.schemas.plan import EditPlan, PlanAction, PlanItem
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing


def _transcript(words: list[tuple[str, float, float]], duration: float = 30.0) -> Transcript:
    tokens = [TranscriptToken(type=TokenType.WORD, text=t, start=s, end=e) for t, s, e in words]
    return Transcript(
        source_id="kamera", source_fingerprint="x", duration=duration, provider="test",
        tokens=synthesize_spacing(tokens),
    )  # fmt: skip


#: One take, three sentences, each a beat of its own in the plan. Between the
#: first two the speaker pauses a quarter of a second; before the third, two.
TAKE = _transcript(
    [("Zacznij", 1.0, 1.4), ("od", 1.45, 1.55), ("planu.", 1.6, 2.1),
     ("Potem", 2.36, 2.7), ("sprawdź", 2.75, 3.2), ("czas.", 3.25, 3.7),
     ("Na", 5.7, 5.8), ("końcu", 5.85, 6.2), ("odpocznij.", 6.25, 6.9)]
)  # fmt: skip


def _plan(*items: PlanItem) -> EditPlan:
    return EditPlan(goal="Trzy zdania, trzy sceny.", items=list(items))


def _keep(start: float, end: float, beat: str, **look) -> PlanItem:
    return PlanItem(
        action=PlanAction.KEEP, source="kamera", start=start, end=end, beat=beat, **look
    )


def test_passages_that_follow_each_other_are_not_cut_apart() -> None:
    edl = compile_plan(
        _plan(_keep(1.0, 2.1, "Plan"), _keep(2.36, 3.7, "Czas"), _keep(5.7, 6.9, "Odpoczynek")),
        TAKE,
        load_profile("talking-head"),
    )
    first, second, third = edl.ranges

    assert first.end == second.start, "they meet at one moment in the pause"
    assert 2.1 <= first.end <= 2.36
    assert second.transition_in == CONTINUOUS and second.runs_on
    assert "runs on from the range before" in second.reason
    assert [r.beat for r in edl.ranges] == ["Plan", "Czas", "Odpoczynek"], "scenes stay apart"
    assert third.transition_in == "cut" and third.start - second.end > 1.5, "a real cut stays"
    assert Timeline(edl).cut_boundaries() == [pytest.approx(second.end - first.start, abs=0.01)]


def test_ranges_padded_into_the_same_pause_no_longer_play_it_twice() -> None:
    """Padding on both sides of a short pause used to overlap the two ranges."""
    close = _transcript(
        [("Zacznij", 1.0, 1.4), ("teraz.", 1.45, 2.0),
         ("Potem", 2.06, 2.5), ("odpocznij.", 2.55, 3.2)]
    )  # fmt: skip
    edl = compile_plan(
        _plan(_keep(1.0, 2.0, "Start"), _keep(2.06, 3.2, "Koniec")),
        close,
        load_profile("calm-expert"),
    )
    first, second = edl.ranges

    assert first.end == second.start
    assert 2.0 <= first.end <= 2.06, "inside the pause, cutting neither word"
    assert sum(r.end - r.start for r in edl.ranges) == pytest.approx(second.end - first.start)


def test_a_change_of_framing_keeps_the_sound_running() -> None:
    edl = compile_plan(
        _plan(_keep(1.0, 2.1, "Plan"), _keep(2.36, 3.7, "Czas", zoom=1.12)),
        TAKE,
        load_profile("talking-head"),
    )
    _first, second = edl.ranges

    assert second.transition_in == PUNCH and second.runs_on
    assert "only the framing changes" in second.reason
    assert Timeline(edl).cut_boundaries() == []


def test_different_recordings_and_real_gaps_are_left_as_cuts() -> None:
    ranges = [
        EDLRange(source="kamera", start=1.0, end=2.0),
        EDLRange(source="telefon", start=2.05, end=3.0),
        EDLRange(source="telefon", start=3.6, end=4.5),
        EDLRange(source="telefon", start=4.55, end=5.5, speed=1.5),
    ]

    joined = join_seams(ranges, 0.25)

    assert [r.transition_in for r in joined] == ["cut", "cut", "cut", "cut"]
    assert [(r.start, r.end) for r in joined] == [(r.start, r.end) for r in ranges]


def test_a_running_seam_lands_on_the_frame_grid_at_render() -> None:
    edl = EDL(
        output_fps="30",
        ranges=[
            EDLRange(source="kamera", start=1.0, end=2.213),
            EDLRange(source="kamera", start=2.213, end=3.7, transition_in=CONTINUOUS),
            EDLRange(source="kamera", start=5.6, end=6.9),
        ],
    )

    aligned = align_running_seams(edl, "30")
    first, second, third = aligned.ranges

    frames = (first.end - first.start) * 30
    assert frames == pytest.approx(round(frames), abs=1e-4), "a whole number of frames"
    assert first.end == second.start and abs(first.end - 2.213) <= 0.5 / 30 + 1e-6
    assert (third.start, third.end) == (5.6, 6.9), "a real cut is not moved"
    assert allocate_range_frames(aligned, "30") == allocate_range_frames(edl, "30")
    assert sum(r.end - r.start for r in aligned.ranges) == pytest.approx(
        sum(r.end - r.start for r in edl.ranges)
    )
    assert align_running_seams(EDL(ranges=edl.ranges[2:]), "30").ranges == edl.ranges[2:]
    assert float(Fraction("30")) == 30.0


def test_no_fade_where_the_sound_runs_on() -> None:
    assert audio_cut_fades(2.0).count("afade") == 2
    assert audio_cut_fades(2.0, at_start=False) == "afade=t=out:st=1.9700:d=0.0300"
    assert audio_cut_fades(2.0, at_end=False) == "afade=t=in:st=0:d=0.0300"
    assert audio_cut_fades(2.0, at_start=False, at_end=False) == "anull"


def _two_ranges(second_start: float, **second) -> EDL:
    return EDL(
        ranges=[
            EDLRange(source="kamera", start=1.0, end=2.14),
            EDLRange(source="kamera", start=second_start, end=6.9, **second),
        ]
    )


def test_a_short_jump_mid_speech_gets_a_change_of_framing() -> None:
    """Half a second removed while the speaker keeps talking used to get nothing."""
    speech = _transcript(
        [("Zacznij", 1.0, 1.4), ("od", 1.45, 1.55), ("planu.", 1.6, 2.1),
         ("yyy", 2.2, 2.5), ("Potem", 2.66, 3.0), ("sprawdź", 3.05, 3.5), ("czas.", 3.55, 6.8)]
    )  # fmt: skip

    found = find_accents(speech, _two_ranges(2.64), energy_preset("lively"))

    at_cut = [c for c in found.candidates if c.kind is AccentKind.JUMP]
    assert len(at_cut) == 1 and at_cut[0].range_zoom is not None
    assert at_cut[0].range_zoom.range_index == 1


def test_a_seam_the_recording_runs_on_across_gets_no_accent() -> None:
    found = find_accents(TAKE, _two_ranges(2.14, transition_in=CONTINUOUS), energy_preset("bold"))

    assert not [c for c in found.candidates if c.kind in (AccentKind.JUMP, AccentKind.TRANSITION)]
