"""The composed cover: local typography, never text from an image model."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from social_video.cover import CoverStyle, compose_cover
from social_video.errors import ValidationError
from social_video.imaging import cover_crop, load_image


def _plate(path: Path, size: tuple[int, int] = (1024, 1024)) -> Path:
    Image.new("RGB", size, (90, 40, 140)).save(path)
    return path


def test_a_plate_is_cropped_to_fill_rather_than_padded() -> None:
    assert cover_crop(Image.new("RGB", (1024, 1024)), 1080, 1920).size == (1080, 1920)
    assert cover_crop(Image.new("RGB", (3000, 1000)), 1080, 1920).size == (1080, 1920)


def test_a_cover_over_a_plate_records_what_it_was_built_from(tmp_path: Path) -> None:
    plate = _plate(tmp_path / "plate.png")
    design = compose_cover(
        tmp_path / "cover.jpg",
        title="Nikt ci tego nie powie o montażu",
        subtitle="Trzy błędy, które kosztują zasięgi",
        style=CoverStyle(),
        plate=plate,
    )
    assert design.background == "plate"
    assert design.plate == str(plate)
    assert design.frame_at is None
    assert len(design.sha256) == 64
    with Image.open(design.path) as image:
        assert image.size == (1080, 1920)


def test_a_frame_background_records_the_timestamp_it_came_from(tmp_path: Path) -> None:
    frame = _plate(tmp_path / "frame.png", (1080, 1920))
    design = compose_cover(
        tmp_path / "cover.jpg",
        title="Tytuł",
        style=CoverStyle(),
        frame=frame,
        frame_at=1.25,
    )
    assert design.background == "frame"
    assert design.frame_at == 1.25


def test_polish_diacritics_survive_the_font_check(tmp_path: Path) -> None:
    design = compose_cover(
        tmp_path / "cover.jpg",
        title="Zażółć gęślą jaźń",
        style=CoverStyle(),
    )
    assert design.font_file is not None
    assert load_image(Path(design.path), label="cover").size == (1080, 1920)


def test_a_cover_has_exactly_one_background(tmp_path: Path) -> None:
    plate = _plate(tmp_path / "plate.png")
    with pytest.raises(ValidationError, match="one background"):
        compose_cover(
            tmp_path / "cover.jpg",
            title="Tytuł",
            style=CoverStyle(),
            plate=plate,
            frame=plate,
        )


def test_an_empty_title_is_refused_rather_than_drawn(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="needs a title"):
        compose_cover(tmp_path / "cover.jpg", title="   ", style=CoverStyle())


def test_a_long_title_wraps_and_still_fits_inside_the_canvas(tmp_path: Path) -> None:
    design = compose_cover(
        tmp_path / "cover.jpg",
        title="Bardzo długi tytuł, który musi się zmieścić w kadrze i nadal być czytelny",
        style=CoverStyle(),
    )
    with Image.open(design.path) as image:
        assert image.size == (1080, 1920)


def test_an_unreadably_long_title_is_refused_before_anything_is_drawn(tmp_path: Path) -> None:
    target = tmp_path / "cover.jpg"
    with pytest.raises(ValidationError, match="readable at thumbnail size"):
        compose_cover(target, title="x" * 200, style=CoverStyle())
    assert not target.exists()


def test_a_garbage_plate_is_rejected_with_the_path_named(tmp_path: Path) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    with pytest.raises(ValidationError, match=r"broken\.png"):
        compose_cover(tmp_path / "cover.jpg", title="T", style=CoverStyle(), plate=broken)
