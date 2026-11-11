"""An end card with people on it: portraits, names, handles, what comes next."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError as PydanticValidationError

from social_video.remotion import _element_payload
from social_video.schemas.motion import MotionElement, MotionPlan, Person


def _card(**changes) -> MotionElement:
    fields = {
        "type": "end_card",
        "start": 10.0,
        "end": 12.5,
        "hold": True,
        "layout": "profiles",
        "text": "Dwa głosy, jeden temat",
        "secondary_text": "Do zobaczenia za tydzień",
        "kicker": "Odcinek",
        "series": {"part": 2, "total": 4},
        "next_label": "W następnym odcinku",
        "next_text": "Jak zacząć dzień bez pośpiechu?",
        "people": [
            {"name": "Anna Przykładowa", "handle": "@anna.przyklad"},
            {"name": "Ewa Wzorcowa", "handle": "@ewa.wzor"},
        ],
        "reason": "Plansza serii z dwiema osobami.",
    }
    return MotionElement(**{**fields, **changes})


def test_a_card_with_people_validates_and_keeps_its_parts() -> None:
    card = _card()

    assert [p.name for p in card.people] == ["Anna Przykładowa", "Ewa Wzorcowa"]
    assert card.series is not None and card.series.label == "2/4"
    assert card.kicker == "Odcinek" and card.next_text


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"people": []}, "one to three people"),
        ({"people": [{"name": f"Osoba {n}"} for n in range(4)]}, "at most 3"),
        ({"next_text": None}, "give both"),
        ({"image_asset": "/tlo.png"}, "draws its own background"),
        ({"people": [{"name": "Anna", "image_asset": "/portret.gif"}]}, "must be a .png"),
        (
            {"layout": "overlay", "series": None},
            "only used by an end_card with layout: profiles",
        ),
    ],
)
def test_a_card_that_does_not_add_up_is_refused(changes, message) -> None:
    with pytest.raises(PydanticValidationError, match=message):
        _card(**changes)


def test_people_belong_to_the_profiles_card_only() -> None:
    with pytest.raises(PydanticValidationError, match="layout: profiles"):
        MotionElement(type="callout", start=1, end=2, text="Uwaga", reason="Akcent.",
                      people=[{"name": "Anna"}])  # fmt: skip
    with pytest.raises(PydanticValidationError, match="only used by a hook_title"):
        MotionElement(type="end_card", start=10, end=12, text="Koniec", reason="Koniec.",
                      series={"part": 1, "total": 3})  # fmt: skip


def test_the_compositor_gets_staged_names_and_the_kicker_with_its_part(tmp_path: Path) -> None:
    portrait = tmp_path / "prywatny folder" / "portret anny.png"
    portrait.parent.mkdir()
    Image.new("RGB", (64, 64), (200, 60, 90)).save(portrait)
    card = _card(
        people=[
            Person(name="Anna Przykładowa", handle="@anna.przyklad", image_asset=str(portrait)),
            Person(name="Ewa Wzorcowa"),
        ]
    )
    plan = MotionPlan(rationale="Plansza serii.", elements=[card])

    payload = _element_payload(card, plan, {str(portrait): "motion-plate-0.png"})

    assert payload["kicker"] == "Odcinek 2 / 4"
    assert payload["people"] == [
        {"name": "Anna Przykładowa", "handle": "@anna.przyklad",
         "image_source": "motion-plate-0.png"},
        {"name": "Ewa Wzorcowa", "handle": None, "image_source": None},
    ]  # fmt: skip
    assert "prywatny folder" not in str(payload), "no path from this machine leaves it"
    assert payload["next_text"] == "Jak zacząć dzień bez pośpiechu?"
    assert len(payload["fitted"]["title"]["lines"]) <= 3
    assert "secondary" in payload["fitted"]


def test_a_card_without_a_series_or_kicker_has_none() -> None:
    card = _card(kicker=None, series=None)
    plan = MotionPlan(rationale="Bez serii.", elements=[card])

    assert _element_payload(card, plan, {})["kicker"] is None
