"""A list's points enter on the words that name them."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from social_video.motion.anchors import anchor_to_words
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.motion import AccentKind, MotionElement, MotionElementType, MotionPlan
from tests.unit.test_motion_energy import _found

#: An invented evening: "Najpierw kąpiel, potem bajka, a na koniec bajka i sen."
SPOKEN = [("Najpierw", 2.0, 2.4), ("kąpiel,", 2.4, 2.9), ("potem", 3.6, 3.9),
          ("bajka,", 3.9, 4.4), ("a", 5.0, 5.1), ("na", 5.1, 5.2), ("koniec", 5.2, 5.6),
          ("bajka", 6.0, 6.4), ("i", 6.4, 6.5), ("sen.", 6.5, 7.0)]  # fmt: skip


def _track(shift: float = 0.0) -> CaptionTrack:
    words = [CaptionWord(text=w, start=s + shift, end=e + shift) for w, s, e in SPOKEN]
    return CaptionTrack(
        cues=[
            CaptionCue(index=1, start=words[0].start, end=words[-1].end,
                       text=" ".join(w.text for w in words), words=words)
        ]
    )  # fmt: skip


def _list(**fields) -> MotionElement:
    values = {"start": 1.5, "end": 4.0, "text": "Spróbuj tak", "items": ["Kąpiel", "Bajka"],
              "position": "top", "reason": "The evening, point by point."}  # fmt: skip
    values.update(fields)
    return MotionElement(type=MotionElementType.LIST, **values)


def test_item_anchors_are_words_or_word_and_occurrence_one_per_item() -> None:
    element = _list(item_at_words=["kąpiel", {"word": "bajka", "occurrence": 2}])
    assert element.item_at_words is not None
    assert [(a.word, a.occurrence) for a in element.item_at_words] == [
        ("kąpiel", 1),
        ("bajka", 2),
    ]
    with pytest.raises(ValidationError, match="needs 2 item_at_words, one per item"):
        _list(item_at_words=["kąpiel"])
    with pytest.raises(ValidationError, match="not a callout"):
        MotionElement(type="callout", start=1, end=3, text="Pytanie?", items=[],
                      item_at_words=["kąpiel"], reason="r")  # fmt: skip
    with pytest.raises(ValidationError, match="go backwards"):
        _list(item_times=[3.0, 2.0])
    with pytest.raises(ValidationError, match="while it is on screen"):
        _list(item_times=[1.6, 4.5])


def test_a_try_this_list_shows_each_point_on_its_word() -> None:
    plan = MotionPlan(rationale="r", elements=[_list(item_at_words=["kąpiel", "bajka"])])

    anchored, notes = anchor_to_words(plan, _track())

    element = anchored.elements[0]
    assert element.item_times == pytest.approx([2.4, 3.9])
    # The title keeps its start; the card stays until the last point has been read.
    assert element.start == pytest.approx(1.5)
    assert element.end == pytest.approx(3.9 + 1.5)
    assert notes == [
        "list item 1 on 'kąpiel' placed at 2.40s",
        "list item 2 on 'bajka' placed at 3.90s",
        "list now on screen 1.50-5.40s to show its items as said",
    ]
    again, quiet = anchor_to_words(anchored, _track())
    assert again.elements[0] == element and quiet == []


def test_the_second_occurrence_and_a_moved_cut_move_the_card_with_its_words() -> None:
    plan = MotionPlan(
        rationale="r",
        elements=[_list(item_at_words=["kąpiel", {"word": "bajka", "occurrence": 2}])],
    )
    first, _notes = anchor_to_words(plan, _track())
    assert first.elements[0].item_times == pytest.approx([2.4, 6.0])

    # A recompile moves the speech 1.25 s later: the whole card follows.
    moved, notes = anchor_to_words(first, _track(shift=1.25))
    element = moved.elements[0]
    assert element.item_times == pytest.approx([3.65, 7.25])
    assert element.start == pytest.approx(first.elements[0].start + 1.25)
    assert element.end == pytest.approx(first.elements[0].end + 1.25)
    assert any("item 2 on 'bajka' placed at 7.25s" in note for note in notes)


def test_a_point_nobody_says_or_says_out_of_order_is_an_error() -> None:
    missing = MotionPlan(rationale="r", elements=[_list(item_at_words=["kąpiel", "mleko"])])
    with pytest.raises(ValueError, match="'mleko' is said 0 time"):
        anchor_to_words(missing, _track())
    backwards = MotionPlan(rationale="r", elements=[_list(item_at_words=["sen", "kąpiel"])])
    with pytest.raises(ValueError, match="said out of order"):
        anchor_to_words(backwards, _track())
    with pytest.raises(ValueError, match="need the caption track"):
        anchor_to_words(backwards, None)


def test_steps_without_anchors_are_revealed_evenly_as_before() -> None:
    steps = MotionElement(type="steps", start=1.0, end=4.0, items=["Kąpiel", "Bajka"],
                          reason="r")  # fmt: skip
    plan = MotionPlan(rationale="r", elements=[steps])
    assert anchor_to_words(plan, None) == (plan, [])


def test_suggested_steps_are_anchored_to_the_words_that_start_them() -> None:
    steps = {c.kind: c for c in _found("bold").candidates}[AccentKind.STEPS].element
    assert steps is not None and steps.item_at_words is not None
    assert [a.word for a in steps.item_at_words] == ["napisy", "hook"]
    assert all(a.occurrence == 1 for a in steps.item_at_words)


def test_a_list_is_never_held_past_the_end_of_the_edit() -> None:
    plan = MotionPlan(rationale="r", elements=[_list(end=6.5, item_at_words=["kąpiel", "sen"])])
    anchored, _ = anchor_to_words(plan, _track(), duration=7.2)
    # The last point (6.5 s) would stay to 8.0 s; the edit ends at 7.2 s.
    assert anchored.elements[0].end == pytest.approx(7.2)
