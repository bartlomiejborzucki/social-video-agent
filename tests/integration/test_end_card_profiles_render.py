"""The profiles end card is drawn: portraits, the next-up box, the brand's colours."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from social_video.schemas.motion import MotionElement, MotionPlan
from tests.integration.test_word_synced_render import (  # noqa: F401
    HEIGHT,
    WIDTH,
    _render,
    pytestmark,
)


def _near(frame: np.ndarray, colour: tuple[int, int, int], tolerance: int = 40) -> np.ndarray:
    return np.abs(frame - np.array(colour)).sum(axis=2) < tolerance


def test_portraits_names_and_the_next_box_are_drawn(tmp_path: Path) -> None:
    portrait = tmp_path / "portret.png"
    Image.new("RGB", (400, 400), (20, 40, 230)).save(portrait)
    card = MotionElement(
        type="end_card", start=0.5, end=4.0, layout="profiles", text="Dwa głosy, jeden temat",
        secondary_text="Do zobaczenia za tydzień", kicker="Odcinek", series={"part": 2, "total": 4},
        next_label="W następnym odcinku", next_text="Jak zacząć dzień bez pośpiechu?",
        people=[
            {"name": "Anna Przykładowa", "handle": "@anna.przyklad",
             "image_asset": str(portrait)},
            {"name": "Ewa Wzorcowa", "handle": "@ewa.wzor"},
        ],
        reason="Plansza serii.",
    )  # fmt: skip
    plan = MotionPlan(
        rationale="Plansza serii z dwiema osobami.",
        accent_color="#E02040",
        background_color="#F4F1EA",
        text_color="#1B2233",
        elements=[card],
    )

    frame, _features = _render(tmp_path, plan, secondary_colour="#2B3A67")
    shown = frame(3.0)

    left, right = shown[:, : WIDTH // 2], shown[:, WIDTH // 2 :]
    blue = _near(shown, (20, 40, 230), 60)
    assert blue[:, : WIDTH // 2].sum() > 800, "the portrait is drawn, on the left"
    assert blue[:, WIDTH // 2 :].sum() < blue[:, : WIDTH // 2].sum() / 10
    # The person without a picture gets initials on the second colour.
    assert _near(right, (43, 58, 103)).sum() > 800
    # The next-up box in the accent, under the portraits.
    lower = shown[int(HEIGHT * 0.6) :]
    assert _near(lower, (224, 32, 64)).sum() > 1500
    # A light card: most of it is the background colour, not the black base.
    assert _near(shown, (244, 241, 234), 50).mean() > 0.2
    assert left.mean() > 100
    # Before it enters the base video is still black.
    assert frame(0.2).mean() < 12
