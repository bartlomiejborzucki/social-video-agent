"""An image card over the speaker: where it sits, measured from the picture itself.

An inset shows a picture or a short clip from the project (a comment, a book
page, an earlier reel) as a card with rounded corners while the speaker stays
in the shot. Its width is set by the plan; its height follows the picture's
own proportions, capped so the card never takes over the frame. The
compositor draws the card at the box computed here and motion QA measures the
same box against the face and the mouth.
"""

from __future__ import annotations

from pathlib import Path

from social_video.schemas.motion import INSET_MAX_HEIGHT, ElementPosition, MotionElement

#: Clear space between the top safe margin and the card, in 1920-high pixels.
TOP_GAP = 10


def inset_aspect(element: MotionElement) -> float:
    """Width over height of the inset's picture, read from the file."""
    if element.image_asset:
        from PIL import Image

        with Image.open(Path(element.image_asset).expanduser()) as image:
            width, height = image.size
    else:
        from social_video.ffmpeg.probe import probe

        assert element.video_asset is not None
        info = probe(Path(element.video_asset).expanduser())
        if info.video is None:
            raise ValueError(f"inset clip {element.video_asset} has no video stream")
        width, height = info.video.display_size
    return width / max(height, 1)


def inset_box(
    element: MotionElement,
    aspect: float,
    *,
    width: int = 1080,
    height: int = 1920,
    margins: dict[str, float] | None = None,
) -> tuple[float, float, float, float]:
    """The card's (left, top, right, bottom), as fractions of the frame."""
    margins = margins or {}
    card_w = element.size_pct / 100.0
    card_h = card_w * width / aspect / height
    if card_h > INSET_MAX_HEIGHT:
        card_w *= INSET_MAX_HEIGHT / card_h
        card_h = INSET_MAX_HEIGHT
    left = (1.0 - card_w) / 2
    if element.placement is ElementPosition.CENTER:
        top = (1.0 - card_h) / 2
    else:
        top = margins.get("top", 6.0) / 100.0 + TOP_GAP / 1920
    return left, top, left + card_w, top + card_h
