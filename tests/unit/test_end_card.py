"""The end card: links kept whole, held after the last word, to the last frame."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from social_video.edl.timeline import Timeline
from social_video.ffmpeg.fonts import default_caption_font
from social_video.motion.layout import held_end_card
from social_video.motion.sfx import sync_sfx
from social_video.motion.text_fit import fit_text, is_address
from social_video.qa.opening import end_card_violations
from social_video.remotion import end_card_text
from social_video.schemas.edl import EDL, EDLRange, Overlay, OverlayKind, SoundEffect
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan

URL = "przyklad-marki.example/strona-z-zapisami/"


def _card(**fields) -> MotionElement:
    values = {"start": 44.0, "end": 46.6, "text": "Nowy poradnik", "reason": "r"}
    values.update(fields)
    return MotionElement(type=MotionElementType.END_CARD, **values)


def test_addresses_are_recognised() -> None:
    assert is_address(URL)
    assert is_address("https://example.com/a-b")
    assert is_address("kontakt@example.com")
    assert not is_address("strona-z-zapisami")
    assert not is_address("Premiera:")


def test_a_long_link_is_never_split_and_the_font_shrinks_to_fit() -> None:
    font = default_caption_font()
    text = f"Zapisz się na listę\n{URL}"
    fitted = fit_text(
        text, max_width=600, base_px=72, min_px=20, font_file=font.path if font else None
    )
    assert URL in fitted.lines
    assert all(line == URL or URL not in line for line in fitted.lines)
    assert fitted.font_px < 72
    assert not any(line.endswith("-") for line in fitted.lines)


def test_text_that_cannot_fit_is_refused_with_the_piece_that_would_not() -> None:
    with pytest.raises(ValueError, match="longest unbreakable piece"):
        fit_text(URL * 3, max_width=300, base_px=72, min_px=40, font_file=None)


def test_end_card_payload_scales_with_the_frame() -> None:
    card = _card(text=f"Nowy poradnik\n{URL}", secondary_text="Premiera: wkrótce")
    full = end_card_text(card, width=1080, height=1920, font=None)
    small = end_card_text(card, width=540, height=960, font=None)
    assert URL in full["title"]["lines"]
    assert small["title"]["font_px"] < full["title"]["font_px"]
    assert full["secondary"]["lines"] == ["Premiera: wkrótce"]


def test_hold_and_layout_belong_to_an_end_card() -> None:
    with pytest.raises(ValidationError, match="only used by an end_card"):
        MotionElement(type=MotionElementType.CTA, start=0, end=2, text="Zapisz", reason="r",
                      hold=True)  # fmt: skip
    with pytest.raises(ValidationError, match="needs an image_asset"):
        _card(layout="image_top")


def test_a_held_end_card_extends_the_edit_and_moves_after_the_last_word() -> None:
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=40.0)])
    plan = MotionPlan(rationale="r", elements=[_card(start=37.0, end=39.6, hold=True)])
    held, placed, note = held_end_card(plan, edl)
    assert note is not None
    assert held.end_hold == pytest.approx(2.6)
    assert held.total_duration == pytest.approx(42.6)
    assert Timeline(held).duration == pytest.approx(42.6)
    assert Timeline(held).content_end == pytest.approx(40.0)
    card = placed.elements[0]
    assert (card.start, card.end) == pytest.approx((40.0, 42.6))
    # Idempotent: a second pass changes nothing.
    assert held_end_card(placed, held)[2] is None
    # Without a held card the hold goes away again.
    plain = MotionPlan(rationale="r", elements=[_card(start=37.0, end=40.0)])
    unheld, _plan, note = held_end_card(plain, held)
    assert unheld.end_hold == 0 and note is not None


def test_a_motion_film_in_place_of_the_held_card_keeps_the_hold() -> None:
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=40.0)])
    plan = MotionPlan(rationale="r", elements=[_card(start=37.0, end=39.6, hold=True)])
    held, _placed, _note = held_end_card(plan, edl)
    # `motion film import` takes the card out of the plan and lays the film's
    # scene over the hold; the times are frames, so a little off.
    film = Overlay(file="film-end.mp4", kind=OverlayKind.MOTION_FILM,
                   start_in_output=40.02, duration=2.58, reason="r")  # fmt: skip
    imported = held.model_copy(update={"overlays": [film]})
    empty = MotionPlan(rationale="r", elements=[])
    kept, _plan, note = held_end_card(empty, imported)
    assert note is None and kept.end_hold == pytest.approx(2.6)
    # A film scene somewhere else does not hold the end.
    early = film.model_copy(update={"start_in_output": 20.0})
    gone, _plan, note = held_end_card(empty, held.model_copy(update={"overlays": [early]}))
    assert gone.end_hold == 0 and note == "end hold removed: no held end_card"


def _slowed() -> EDL:
    # A slowed range: the speech ends at 12.99659...s, which rounds up.
    return EDL(ranges=[EDLRange(source="a", start=0, end=5.3, speed=0.9),
                       EDLRange(source="a", start=7.1, end=14.2077)])  # fmt: skip


def test_a_sound_effect_on_the_held_card_entrance_is_part_of_the_edit(tmp_path: Path) -> None:
    plan = MotionPlan(rationale="r", elements=[_card(start=10.0, end=12.5, hold=True)])
    held, placed, _note = held_end_card(plan, _slowed())
    assert placed.elements[0].start > Timeline(held).content_end
    (tmp_path / "pop.wav").write_bytes(b"")

    with_sfx, added = sync_sfx(held, placed, tmp_path)

    assert [e.at for e in added] == [placed.elements[0].start]

    # Inside the hold too; only past the held end is refused.
    def effect_at(at: float) -> EDL:
        effect = SoundEffect(path="pop.wav", at=at, reason="r")
        return EDL.model_validate(
            with_sfx.model_copy(update={"sound_effects": [effect]}).model_dump()
        )

    assert effect_at(14.5).sound_effects[0].at == 14.5
    with pytest.raises(ValidationError, match=r"lands after the 15\.50s output"):
        effect_at(16.0)


def test_the_entrance_effect_follows_the_card_and_leaves_with_the_hold(tmp_path: Path) -> None:
    plan = MotionPlan(rationale="r", elements=[_card(start=10.0, end=12.5, hold=True)])
    held, placed, _note = held_end_card(plan, _slowed())
    (tmp_path / "pop.wav").write_bytes(b"")
    with_sfx, _added = sync_sfx(held, placed, tmp_path)

    # A recompile cuts the last range shorter: card and effect move together.
    shorter = with_sfx.model_copy(update={"ranges": [*with_sfx.ranges[:1],
                                  EDLRange(source="a", start=7.1, end=13.0)]})  # fmt: skip
    moved, moved_plan, _note = held_end_card(placed, shorter)
    assert [e.at for e in moved.sound_effects] == [moved_plan.elements[0].start]

    # The card is no longer held: the effect it carried goes with the hold.
    plain = MotionPlan(rationale="r", elements=[_card(start=9.0, end=11.0)])
    unheld, _plan, note = held_end_card(plain, moved)
    assert unheld.end_hold == 0 and unheld.sound_effects == []
    assert note == "end hold removed: no held end_card; 1 sound effect(s) after the new end dropped"


def test_an_explanation_then_a_call_to_action_follow_the_last_word_in_turn() -> None:
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=40.0)])
    why = _card(start=30.0, end=33.0, text="Dlaczego tak działa", hold=True)
    cta = _card(start=36.0, end=38.5, text="Zapisz na wieczór", hold=True)
    plan = MotionPlan(rationale="r", elements=[cta, why])

    held, placed, note = held_end_card(plan, edl)

    assert note == "2 end_cards held 5.50s after the last word, 40.00-45.50s"
    assert held.end_hold == pytest.approx(5.5)
    assert [(e.text, e.start, e.end) for e in placed.elements] == [
        ("Dlaczego tak działa", 40.0, 43.0),
        ("Zapisz na wieczór", 43.0, 45.5),
    ]
    assert held_end_card(placed, held)[2] is None
    # Both count as the end of the reel; a card left mid-edit does not.
    assert end_card_violations(held, placed) == []
    early = placed.model_copy(update={"elements": [placed.elements[0].model_copy(
        update={"start": 20.0, "end": 23.0, "hold": False}), placed.elements[1]]})  # fmt: skip
    assert [v.where for v in end_card_violations(held, early)] == ["end_card at 20.00s"]


def test_held_end_cards_longer_than_the_hold_allows_are_refused() -> None:
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=40.0)])
    cards = [_card(start=30.0, end=36.0, hold=True), _card(start=36.0, end=41.0, hold=True)]
    with pytest.raises(ValueError, match=r"last 11\.00s together"):
        held_end_card(MotionPlan(rationale="r", elements=cards), edl)
