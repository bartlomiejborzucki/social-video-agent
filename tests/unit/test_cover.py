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


LONG_TITLE = "Trzy błędy, które zabijają zasięgi Twoich rolek"


@pytest.mark.parametrize("layout", ["bottom", "top", "boxed", "number"])
def test_every_layout_keeps_its_type_inside_the_profile_grid(tmp_path: Path, layout: str) -> None:
    design = compose_cover(
        tmp_path / f"{layout}.jpg",
        title=LONG_TITLE,
        subtitle="Zażółć gęślą jaźń",
        style=CoverStyle(),
        plate=_plate(tmp_path / "plate.png"),
        layout=layout,  # type: ignore[arg-type]
        figure="3" if layout == "number" else None,
    )
    assert design.layout == layout
    assert design.grid_safe is True
    left, top, right, bottom = design.text_box or []
    assert 240 <= top < bottom <= 1680
    assert 0 <= left < right <= 1080


def test_top_and_bottom_put_the_type_where_they_say(tmp_path: Path) -> None:
    plate = _plate(tmp_path / "plate.png")
    top = compose_cover(
        tmp_path / "t.jpg", title="Tytuł", style=CoverStyle(), plate=plate, layout="top"
    )
    bottom = compose_cover(tmp_path / "b.jpg", title="Tytuł", style=CoverStyle(), plate=plate)
    assert (top.text_box or [])[3] < 960 < (bottom.text_box or [])[1]


def test_grid_band_only_crops_tall_covers() -> None:
    from social_video.cover import grid_band

    assert grid_band(1080, 1920) == (240, 1680)
    assert grid_band(1080, 1350) == (0, 1350)
    assert grid_band(1080, 1080) == (0, 1080)


def test_the_number_layout_needs_a_short_figure(tmp_path: Path) -> None:
    target = tmp_path / "cover.jpg"
    with pytest.raises(ValidationError, match="--figure"):
        compose_cover(target, title="T", style=CoverStyle(), layout="number")
    with pytest.raises(ValidationError, match="keep it to 8"):
        compose_cover(target, title="T", style=CoverStyle(), layout="number", figure="123456789")
    with pytest.raises(ValidationError, match="only by the number layout"):
        compose_cover(target, title="T", style=CoverStyle(), figure="3")
    assert not target.exists()


def test_boxed_type_is_dark_on_a_light_accent() -> None:
    from social_video.cover import _ink_on

    style = CoverStyle(accent="#FFD400", text_colour="#FFFFFF", background_colour="#101114")
    assert _ink_on("#FFD400", style) == "#101114"
    assert _ink_on("#1A237E", style) == "#FFFFFF"


def test_several_layouts_compare_side_by_side(tmp_path: Path) -> None:
    from social_video.cover import compare_covers

    plate = _plate(tmp_path / "plate.png")
    designs = [
        compose_cover(tmp_path / f"{layout}.jpg", title="Tytuł", style=CoverStyle(),
                      plate=plate, layout=layout)  # type: ignore[arg-type]
        for layout in ("bottom", "boxed")
    ]  # fmt: skip
    sheet = compare_covers(designs, tmp_path / "sheet.png", tile_width=200)
    with Image.open(sheet) as image:
        assert image.size == (404, round(1920 * 200 / 1080))


def test_the_cli_draws_a_review_sheet_without_choosing_a_cover(tmp_path: Path) -> None:
    import json

    from typer.testing import CliRunner

    from social_video.cli import app

    workspace = tmp_path / "edit"
    plate = _plate(tmp_path / "plate.png")
    args = ["cover", str(workspace), "--title", "Tytuł", "--plate", str(plate)]
    result = CliRunner().invoke(
        app, [*args, "--layout", "top", "--layout", "number", "--figure", "3", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [c["layout"] for c in payload["covers"]] == ["top", "number"]
    assert payload["covers"][1]["figure"] == "3"
    assert Path(payload["sheet"]).is_file()
    assert not (workspace / "cover.json").exists()

    single = CliRunner().invoke(app, [*args, "--layout", "boxed", "--json"])
    assert single.exit_code == 0, single.output
    assert json.loads(single.output)["layout"] == "boxed"
    assert (workspace / "cover.json").is_file()
