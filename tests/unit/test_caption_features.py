"""The default renderer must draw the caption features the contract asks for."""

from __future__ import annotations

from pathlib import Path

from social_video.captions.features import caption_features, highlight_possible
from social_video.qa.brand import check_brand
from social_video.remotion import _caption_payload
from social_video.schemas.brand import BrandProfile, CaptionCase, CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.config import BrandContract
from social_video.schemas.motion import MotionElement, MotionElementType
from social_video.schemas.qa import RenderManifest


def _track(with_words: bool = True) -> CaptionTrack:
    words = [
        CaptionWord(text="to", start=0.0, end=0.4),
        CaptionWord(text="jest", start=0.4, end=0.7),
        CaptionWord(text="żart", start=0.7, end=1.0),
    ]
    return CaptionTrack(
        cues=[
            CaptionCue(
                index=1,
                start=0.0,
                end=1.0,
                text="TO JEST ŻART",
                words=words if with_words else [],
            )
        ]
    )


def test_word_timings_are_only_shipped_when_the_highlight_is_used() -> None:
    style = CaptionStyle(highlight_active_word=True, case=CaptionCase.UPPER)
    track = _track()
    with_highlight = _caption_payload(track, style, highlight=True)
    without = _caption_payload(track, style, highlight=False)
    assert [word["text"] for word in with_highlight[0]["words"]] == ["TO", "JEST", "ŻART"]
    assert "words" not in without[0]


def test_the_style_case_reaches_individual_words() -> None:
    style = CaptionStyle(highlight_active_word=True, case=CaptionCase.AS_SPOKEN)
    payload = _caption_payload(_track(), style, highlight=True)
    assert [word["text"] for word in payload[0]["words"]] == ["to", "jest", "żart"]


def test_a_highlight_needs_word_timings_not_just_the_setting() -> None:
    style = CaptionStyle(highlight_active_word=True)
    assert highlight_possible(style, _track())
    assert not highlight_possible(style, _track(with_words=False))
    assert not highlight_possible(CaptionStyle(highlight_active_word=False), _track())


def test_features_distinguish_applied_from_impossible() -> None:
    style = CaptionStyle(highlight_active_word=True, bold=True)
    assert "active_word_highlight" in caption_features(style, _track(), highlight=True)
    unavailable = caption_features(style, _track(with_words=False), highlight=False)
    assert "active_word_highlight_unavailable" in unavailable


def test_brand_qa_fails_when_the_renderer_dropped_a_contracted_highlight(monkeypatch) -> None:
    style = CaptionStyle(highlight_active_word=True, bold=True)
    contract = BrandContract(
        project_config_path="c.yaml",
        project_config_sha256="b" * 64,
        project_root="/p",
        brand=BrandProfile(captions=style),
        output_width=1080,
        output_height=1920,
        output_fps="30/1",
        safe_margins={"top": 6, "right": 6, "bottom": 12, "left": 6},
    )

    class Video:
        display_size = (1080, 1920)

    class Info:
        video = Video()

    monkeypatch.setattr("social_video.qa.brand.probe", lambda _: Info())
    evidence = style.model_dump(mode="json", exclude={"schema_version"})
    evidence["position"] = style.position.value

    def manifest(features: list[str]) -> RenderManifest:
        return RenderManifest(
            output="final.mp4",
            edl="main",
            rendered_at="2026-09-18T00:00:00Z",
            duration=10,
            width=1080,
            height=1920,
            frame_rate="30/1",
            brand_contract_sha256=contract.project_config_sha256,
            caption_style=evidence,
            caption_renderer="remotion",
            caption_features=features,
            captions_burned=True,
            brand_safe_margins=contract.safe_margins,
        )

    dropped = check_brand(
        Path("final.mp4"), contract, manifest(["burned_in", "bold", "background_none"])
    )
    failed = {check.name for check in dropped.errors}
    assert "caption active-word highlight" in failed

    applied = check_brand(
        Path("final.mp4"),
        contract,
        manifest(["burned_in", "active_word_highlight", "bold"]),
    )
    assert "caption active-word highlight" not in {check.name for check in applied.errors}


def test_an_end_card_may_carry_a_plate_and_other_elements_may_not() -> None:
    card = MotionElement(
        type=MotionElementType.END_CARD,
        start=8.0,
        end=10.0,
        text="Zapisz się",
        reason="Domknięcie z wezwaniem do działania.",
        image_asset="assets/generated/end_card_plate.png",
    )
    assert card.image_asset is not None
    for bad in (MotionElementType.HOOK, MotionElementType.CALLOUT):
        try:
            MotionElement(
                type=bad,
                start=0.0,
                end=1.0,
                text="x",
                reason="r",
                image_asset="plate.png",
            )
        except Exception as exc:
            assert "end_card" in str(exc)
        else:  # pragma: no cover - the validator must reject this
            raise AssertionError(f"{bad} accepted a plate")
