"""The end card: links kept whole, held after the last word, to the last frame."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from social_video.edl.timeline import Timeline
from social_video.ffmpeg.fonts import default_caption_font
from social_video.motion.layout import held_end_card
from social_video.motion.text_fit import fit_text, is_address
from social_video.remotion import end_card_text
from social_video.schemas.edl import EDL, EDLRange
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
