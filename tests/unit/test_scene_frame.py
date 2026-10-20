"""2.3: labels drawn as the title of a scene frame, never like a caption."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from social_video.captions.ass import SceneFrameDrawing, render_boxed_ass
from social_video.captions.fit import layout_captions
from social_video.motion.layout import (
    continues,
    element_band,
    framing_label,
    scene_frame_geometry,
)
from social_video.project_config import compile_brand_contract
from social_video.remotion import render_motion_design
from social_video.schemas.brand import CaptionBackgroundStyle, CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.config import ProjectVideoConfig
from social_video.schemas.motion import (
    ElementPosition,
    MotionElement,
    MotionElementType,
    MotionPlan,
)
from social_video.workspace.layout import Workspace

ROOT = Path(__file__).resolve().parents[2]
STYLE = CaptionStyle(
    font_size_pct=3.6,
    margin_pct=22,
    background_style=CaptionBackgroundStyle.ROUNDED_BOX,
    background_colour="#28BCA5",
    corner_radius=24,
)


def _label(text: str, start: float, end: float) -> MotionElement:
    return MotionElement(
        type=MotionElementType.LABEL, start=start, end=end, text=text, reason="Scene name."
    )


def _cue(index: int, start: float, end: float, text: str = "Mamo, pobaw się") -> CaptionCue:
    return CaptionCue(index=index, start=start, end=end, text=text)


# -- config and contract ------------------------------------------------------


def test_label_style_defaults_to_chip_and_rejects_unknown_styles() -> None:
    assert ProjectVideoConfig().label_style == "chip"
    assert ProjectVideoConfig(label_style="scene_frame").label_style == "scene_frame"
    with pytest.raises(ValueError, match="label_style"):
        ProjectVideoConfig(label_style="banner")


def test_the_secondary_colour_comes_from_the_brand_unless_set() -> None:
    brand = ["#28BCA5", "#394463", "#D23150"]
    assert ProjectVideoConfig(brand_colors=brand).secondary_colour == "#394463"
    assert ProjectVideoConfig(brand_colors=brand, secondary_color="#d23150").secondary_colour == (
        "#D23150"
    )
    lone = ProjectVideoConfig(brand_colors=["#28BCA5"])
    assert lone.secondary_colour == lone.caption_style.outline_color
    with pytest.raises(ValueError, match="RRGGBB"):
        ProjectVideoConfig(secondary_color="navy")


def test_hold_through_pauses_has_a_top_level_shorthand() -> None:
    assert ProjectVideoConfig().hold_through_pauses is False
    assert ProjectVideoConfig(caption_hold_through_pauses=True).hold_through_pauses is True
    nested = ProjectVideoConfig(caption_style={"hold_through_pauses": True})
    assert nested.hold_through_pauses is True


def test_the_contract_carries_the_label_style_and_colours(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True)
    (project / "assets" / "Lato.ttf").write_bytes(b"fixture-font")
    config = project / "social-video.yaml"
    config.write_text(
        "schema_version: 1\nfont: Lato\nfont_file: assets/Lato.ttf\n"
        'brand_colors: ["#28BCA5", "#394463"]\nlabel_style: scene_frame\n'
        "caption_hold_through_pauses: true\n",
        encoding="utf-8",
    )
    contract = compile_brand_contract(config, Workspace.at(tmp_path / "edit"))
    assert contract.brand.label_style == "scene_frame"
    assert contract.brand.secondary_colour == "#394463"
    assert contract.brand.accent_colour == "#28BCA5"
    assert contract.brand.captions.hold_through_pauses is True


# -- placement ----------------------------------------------------------------


def test_only_movable_elements_take_a_position() -> None:
    cta = MotionElement(type=MotionElementType.CTA, start=0, end=2, text="Zapisz", reason="r")
    assert cta.placement is ElementPosition.ABOVE_CAPTIONS
    top = cta.model_copy(update={"position": ElementPosition.TOP})
    assert MotionElement.model_validate(top.model_dump()).placement is ElementPosition.TOP
    listed = MotionElement(type="list", start=0, end=3, items=["a", "b"], reason="r")
    assert listed.placement is ElementPosition.CENTER
    with pytest.raises(ValueError, match="accepts position"):
        MotionElement(type="label", start=0, end=2, text="Scena", reason="r", position="top")
    with pytest.raises(ValueError, match="accepts position"):
        MotionElement(type="cta", start=0, end=2, text="Zapisz", reason="r", position="center")


def test_the_frame_scales_with_the_output_height() -> None:
    final = scene_frame_geometry(STYLE, width=1080, height=1920)
    preview = scene_frame_geometry(STYLE, width=720, height=1280)
    ratio = 1280 / 1920
    for name in ("top", "height", "width", "tab_font_px", "border", "caption_centre"):
        assert getattr(preview, name) == pytest.approx(getattr(final, name) * ratio, rel=1e-6)
    # The frame holds the caption band: two lines fit inside it.
    assert final.top < 1920 * (1 - 0.22) - 2 * 1920 * 0.036
    assert final.bottom > 1920 * (1 - 0.22)


def test_a_top_list_is_measured_where_it_is_drawn() -> None:
    listed = MotionElement(
        type="list", start=0, end=3, items=["a", "b", "c"], reason="r", position="top"
    )
    top, bottom = element_band(listed, height=1920, margins={"top": 10})
    assert top == pytest.approx(0.1 + 10 / 1920)
    assert bottom < 0.3
    centred = listed.model_copy(update={"position": None})
    assert element_band(centred, height=1920, margins={"top": 10}) is None


def test_continuation_and_framing_follow_the_label_times() -> None:
    first, second, apart = _label("Częsty odruch", 0, 3), _label("Spróbuj tak", 3.02, 6), None
    apart = _label("Na koniec", 7, 9)
    elements = [first, second, apart]
    assert continues(second, elements) is first
    assert continues(first, elements) is None
    assert continues(apart, elements) is None
    assert framing_label(2.0, 4.5, elements) is second
    assert framing_label(6.1, 6.8, elements) is None


# -- renderers ----------------------------------------------------------------


def test_the_ass_route_draws_the_same_frame_and_flips_the_title() -> None:
    track = CaptionTrack(cues=[_cue(1, 0.0, 2.0), _cue(2, 6.2, 6.9)])
    layout = layout_captions(list(track.cues), STYLE, width=1080, height=1920)
    geometry = scene_frame_geometry(STYLE, width=1080, height=1920)
    scene = SceneFrameDrawing(
        geometry=geometry,
        labels=[_label("Częsty odruch", 0, 3), _label("Spróbuj tak", 3, 6)],
        accent="#28BCA5",
        secondary="#394463",
    )
    document = render_boxed_ass(track, STYLE, layout, width=1080, height=1920, scene=scene)
    events = [line for line in document.splitlines() if line.startswith("Dialogue:")]
    frames = [e for e in events if f"\\pos({round(geometry.left)},{round(geometry.top)})" in e]
    assert len(frames) == 2, "one frame per label"
    assert "\\3c&H00A5BC28" in frames[1], "the continued scene flashes the accent rim"
    titles = [e for e in events if "CZĘSTY ODRUCH" in e or "SPRÓBUJ TAK" in e]
    assert any("\\t(0," in e and "\\fscy0)" in e for e in titles), "old title flips away"
    assert any("\\fscy0\\t(0," in e for e in titles), "new title flips in"
    # The framed cue sits centred in the frame; the one after the labels does not.
    boxes = [e for e in events if e.startswith("Dialogue: 0,") and e not in frames]
    framed_top = int(boxes[0].split("\\pos(")[1].split(",")[1].split(")")[0])
    drawn = layout.cues[0]
    box_h = len(drawn.lines) * drawn.font_size_px * layout.line_height + 31
    assert framed_top == pytest.approx(geometry.caption_centre - box_h / 2, abs=1)
    free_top = int(boxes[1].split("\\pos(")[1].split(",")[1].split(")")[0])
    assert free_top != framed_top


def test_the_compositor_gets_the_frame_and_the_framed_cues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not (ROOT / "node_modules/remotion").is_dir():
        pytest.skip("Remotion dependencies not installed")
    source = tmp_path / "base.mp4"
    source.write_bytes(b"video")
    plan = MotionPlan(
        rationale="Two scenes.",
        elements=[_label("Częsty odruch", 0, 3), _label("Spróbuj tak", 3, 6)],
    )
    track = CaptionTrack(cues=[_cue(1, 0.0, 2.0), _cue(2, 6.2, 6.9)])
    props: dict = {}

    def fake_run(args, **kwargs):
        props.update(json.loads(Path(args[-2]).read_text(encoding="utf-8")))
        Path(args[-1]).write_bytes(b"rendered")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("social_video.remotion._verify_staged_output", lambda *a, **k: None)
    monkeypatch.setattr(
        "social_video.remotion.mux_base_audio",
        lambda picture, base, output: output.write_bytes(picture.read_bytes()) and output,
    )
    _out, features, _layout = render_motion_design(
        source, tmp_path / "out.mp4", plan, duration_in_frames=240, fps=30, width=1080,
        height=1920, staging_root=tmp_path / "cache", captions=track, caption_style=STYLE,
        label_style="scene_frame", secondary_colour="#394463",
        safe_margins={"top": 10, "right": 8, "bottom": 22, "left": 8},
    )  # fmt: skip
    assert "scene_frame" in features
    assert props["labelStyle"] == "scene_frame"
    assert props["secondaryColor"] == "#394463"
    assert props["sceneFrame"]["width"] == pytest.approx(1080 * 0.88, abs=1)
    assert [c["framed"] for c in props["captions"]] == [True, False]
    assert [e["continues"] for e in props["elements"]] == [None, "Częsty odruch"]


def test_the_render_says_which_plan_values_the_contract_replaces(tmp_path: Path) -> None:
    from social_video.pipeline import brand_overrides

    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True)
    (project / "assets" / "Lato.ttf").write_bytes(b"fixture-font")
    config = project / "social-video.yaml"
    config.write_text(
        'schema_version: 1\nfont: Lato\nfont_file: assets/Lato.ttf\nbrand_colors: ["#28BCA5"]\n',
        encoding="utf-8",
    )
    contract = compile_brand_contract(config, Workspace.at(tmp_path / "edit"))
    plan = MotionPlan(rationale="r", accent_color="#28bca5", font_family="Inter")
    lines = brand_overrides(plan, contract)
    assert any("font_family 'Inter'" in line and "'Lato'" in line for line in lines)
    assert not any("accent_color" in line for line in lines), "same colour, any case"
    same = plan.model_copy(
        update={
            "font_family": "Lato",
            "text_color": contract.brand.captions.primary_colour,
            "background_color": contract.brand.background_colour,
            "style": contract.brand.style_pack,
        }
    )
    assert brand_overrides(same, contract) == []


def test_ass_type_is_sized_like_the_browser_draws_it() -> None:
    """libass sizes a font by its line height, a browser by its em."""
    from social_video.captions.ass import _line_height_per_em

    font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    if not font.is_file():
        pytest.skip("deterministic test font is unavailable")
    ratio = _line_height_per_em(font)
    assert 1.1 < ratio < 1.3
    assert _line_height_per_em(None) == 1.2
    styled = STYLE.model_copy(update={"font_file": str(font)})
    track = CaptionTrack(cues=[_cue(1, 0.0, 2.0)])
    layout = layout_captions(list(track.cues), styled, width=1080, height=1920, font_file=font)
    document = render_boxed_ass(track, styled, layout, width=1080, height=1920)
    drawn = layout.cues[0].font_size_px
    assert f"\\fs{round(drawn * ratio)}" in document
