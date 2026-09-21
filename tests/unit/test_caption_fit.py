"""Captions are drawn in full or refused. Nothing is ever shortened to fit.

The defect these cover: at 5% of a 1920-pixel frame the Remotion compositor
clamped captions with `-webkit-line-clamp` and `overflow: hidden`, so
`nikomu, udowadniając na siłę` was drawn as `nikomu, udowadniając na...`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from social_video.captions.chunk import build_caption_track
from social_video.captions.fit import (
    ESTIMATED_ADVANCE_EM,
    SHRINK_FLOOR,
    CaptionOverflowError,
    contract_fit_error,
    font_size_px,
    layout_captions,
    text_box_width_px,
)
from social_video.edl.timeline import Timeline
from social_video.schemas.brand import (
    CaptionBackgroundStyle,
    CaptionOutlineStyle,
    CaptionStyle,
)
from social_video.schemas.captions import CaptionCue
from social_video.schemas.config import CaptionConfig, ProjectVideoConfig
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken

#: The words that used to lose their endings. Long, ordinary, and Polish.
LONG_POLISH_WORDS = ("odpowiedzialność", "udowadniając", "wyregulowany", "doświadczać")
#: The phrases from the report, verbatim.
REPORTED_PHRASES = ("nikomu, udowadniając na siłę", "wziąć odpowiedzialność za")
SAFE_MARGINS = {"top": 6.0, "right": 6.0, "bottom": 22.0, "left": 6.0}
REELS = {"width": 1080, "height": 1920}
PREVIEW = {"width": 720, "height": 1280}


@pytest.fixture(scope="module")
def project_font() -> str:
    """A real font file, so widths are measured rather than estimated."""
    proc = subprocess.run(
        ["fc-match", "-f", "%{file}", "Lato:bold"], capture_output=True, text=True, check=False
    )
    path = Path(proc.stdout.strip())
    if proc.returncode != 0 or not path.is_file():
        pytest.skip("no system font available to measure")
    return str(path)


def _reference_style(**changes: object) -> CaptionStyle:
    """The contract the reference project config compiles to."""
    defaults = dict(
        font_size_pct=3.6,
        max_lines=2,
        max_words_per_cue=4,
        max_chars_per_cue=24,
        background_style=CaptionBackgroundStyle.ROUNDED_BOX,
        corner_radius=24,
        margin_pct=22.0,
        outline_or_shadow=CaptionOutlineStyle.NONE,
        outline_width=0.0,
        shadow=0.0,
    )
    return CaptionStyle(**{**defaults, **changes})


def _cues(*texts: str) -> list[CaptionCue]:
    return [
        CaptionCue(index=i, start=float(i), end=float(i) + 1.5, text=text)
        for i, text in enumerate(texts, start=1)
    ]


# --- the reported regression ------------------------------------------------


@pytest.mark.parametrize("geometry", [REELS, PREVIEW], ids=["1080x1920", "720x1280"])
def test_long_polish_phrases_are_drawn_in_full(geometry: dict, project_font: str) -> None:
    cues = _cues(*REPORTED_PHRASES, *(f"{word} dalej" for word in LONG_POLISH_WORDS))

    layout = layout_captions(
        cues,
        _reference_style(),
        **geometry,
        safe_margins=SAFE_MARGINS,
        font_file=project_font,
    )

    assert layout.measured
    for drawn, cue in zip(layout.cues, cues, strict=True):
        assert drawn.text == cue.text, "the drawn lines must reproduce the cue exactly"
        assert len(drawn.lines) <= 2
        assert "..." not in drawn.text and "…" not in drawn.text
    assert layout.max_line_width_px <= layout.text_width_px
    assert layout.evidence()["truncated_cues"] == []


@pytest.mark.parametrize("word", LONG_POLISH_WORDS)
def test_a_long_word_is_never_hyphenated_or_shortened(word: str, project_font: str) -> None:
    layout = layout_captions(
        _cues(word),
        _reference_style(),
        **REELS,
        safe_margins=SAFE_MARGINS,
        font_file=project_font,
    )

    (drawn,) = layout.cues
    assert [line.text for line in drawn.lines] == [word]
    assert "-" not in drawn.text


def test_the_old_five_percent_contract_shrinks_instead_of_clipping(project_font: str) -> None:
    """The size that caused the defect now costs pixels, never characters."""
    style = _reference_style(font_size_pct=5.0)
    cues = _cues(*REPORTED_PHRASES)

    layout = layout_captions(
        cues, style, **REELS, safe_margins=SAFE_MARGINS, font_file=project_font
    )

    assert layout.requested_font_size_px == 96
    assert layout.shrunk_cues == (1, 2)
    assert layout.min_font_size_px >= int(96 * SHRINK_FLOOR)
    for drawn, cue in zip(layout.cues, cues, strict=True):
        assert drawn.text == cue.text


def test_an_unfittable_cue_fails_loudly_rather_than_losing_its_ending(project_font: str) -> None:
    style = _reference_style(font_size_pct=8.0, max_lines=1)

    with pytest.raises(CaptionOverflowError) as caught:
        layout_captions(
            _cues("odpowiedzialność udowadniając"),
            style,
            **REELS,
            safe_margins=SAFE_MARGINS,
            font_file=project_font,
        )

    message = str(caught.value)
    assert "cannot be drawn in full" in message
    assert "odpowiedzialność" in message
    assert "font_size_pct" in message and "max_chars_per_cue" in message


# --- wrapping behaviour -----------------------------------------------------


def test_wrapping_breaks_on_word_boundaries_only(project_font: str) -> None:
    layout = layout_captions(
        _cues("wziąć odpowiedzialność za"),
        _reference_style(),
        **REELS,
        safe_margins=SAFE_MARGINS,
        font_file=project_font,
    )

    (drawn,) = layout.cues
    for line in drawn.lines:
        assert line.text == line.text.strip()
        assert all(piece in ["wziąć", "odpowiedzialność", "za"] for piece in line.text.split())


def test_measurement_falls_back_to_an_estimate_without_a_font_file() -> None:
    layout = layout_captions(
        _cues("wziąć odpowiedzialność za"),
        _reference_style(),
        **REELS,
        safe_margins=SAFE_MARGINS,
        font_file=None,
    )

    assert not layout.measured
    assert layout.evidence()["font_measured"] is False
    # The estimate is deliberately wider than any real font, so a caption laid
    # out without measurement is conservative rather than optimistic.
    assert ESTIMATED_ADVANCE_EM > 0.5


def test_a_narrower_preview_gets_a_proportionally_smaller_caption() -> None:
    style = _reference_style()

    assert font_size_px(style, 1920) == 69
    assert font_size_px(style, 1280) == 46
    assert text_box_width_px(style, 1080, SAFE_MARGINS) > text_box_width_px(
        style, 720, SAFE_MARGINS
    )


# --- the chunker splits before layout ever runs -----------------------------


def test_the_chunker_splits_long_sentences_at_word_boundaries() -> None:
    """Step one of the fix: a cue is short because it was split, not clipped."""
    spoken = "trzeba wziąć odpowiedzialność za to nikomu udowadniając na siłę doświadczać tego"
    tokens = [
        TranscriptToken(text=word, start=i * 0.4, end=i * 0.4 + 0.35, type=TokenType.WORD)
        for i, word in enumerate(spoken.split())
    ]
    transcript = Transcript(
        source_id="s",
        source_fingerprint="f",
        duration=20.0,
        provider="test",
        language="pl",
        tokens=tokens,
    )
    timeline = Timeline(EDL(ranges=[EDLRange(source="s", start=0.0, end=20.0)], output_fps="30/1"))
    style = _reference_style()

    track = build_caption_track(transcript, timeline, style=style)

    assert len(track.cues) > 1
    for cue in track.cues:
        assert len(cue.text) <= style.max_chars_per_cue or len(cue.text.split()) == 1
        assert len(cue.text.split()) <= style.max_words_per_cue
    assert " ".join(cue.text for cue in track.cues) == spoken


# --- the contract cannot express an unrenderable caption --------------------


def test_the_reference_config_values_fit_a_nine_by_sixteen_frame() -> None:
    config = ProjectVideoConfig()
    style = config.caption_style

    assert (style.font_size_pct, style.max_words_per_cue, style.max_chars_per_cue) == (3.6, 4, 24)
    assert (style.outline_or_shadow.value, style.corner_radius, style.bottom_margin_pct) == (
        "none",
        24,
        22,
    )
    assert (
        contract_fit_error(
            font_size_pct=style.font_size_pct,
            max_chars_per_cue=style.max_chars_per_cue,
            max_lines=style.max_lines,
            boxed=True,
            width=1080,
            height=1920,
            horizontal_margin_pct=12,
        )
        is None
    )


def test_config_validation_refuses_a_caption_that_cannot_be_drawn() -> None:
    with pytest.raises(ValueError, match="cannot fit its own text"):
        ProjectVideoConfig(caption_style=CaptionConfig(font_size_pct=8.0, max_chars_per_cue=40))


def test_an_old_config_without_the_new_keys_gets_the_safe_values() -> None:
    """Compatibility: omitting the keys means the reference values, not the old ones."""
    config = ProjectVideoConfig.model_validate(
        {
            "schema_version": 1,
            "brand_name": "Legacy",
            "caption_style": {"case": "as_spoken", "max_lines": 2},
        }
    )

    assert config.caption_style.font_size_pct == 3.6
    assert config.caption_style.max_chars_per_cue == 24


# --- QA sees the geometry, not the intention --------------------------------


def _qa_report(layout_evidence: dict, style: CaptionStyle, monkeypatch) -> object:
    from social_video.qa.brand import check_brand
    from social_video.schemas.brand import BrandProfile
    from social_video.schemas.config import BrandContract
    from social_video.schemas.qa import RenderManifest

    contract = BrandContract(
        project_config_path="c.yaml",
        project_config_sha256="c" * 64,
        project_root="/p",
        brand=BrandProfile(captions=style),
        output_width=1080,
        output_height=1920,
        output_fps="30/1",
        safe_margins=SAFE_MARGINS,
    )

    class Video:
        display_size = (1080, 1920)

    class Info:
        video = Video()

    monkeypatch.setattr("social_video.qa.brand.probe", lambda _: Info())
    evidence = style.model_dump(mode="json", exclude={"schema_version"})
    evidence["position"] = style.position.value
    manifest = RenderManifest(
        output="final.mp4",
        edl="main",
        rendered_at="2026-09-21T00:00:00Z",
        duration=10,
        width=1080,
        height=1920,
        frame_rate="30/1",
        brand_contract_sha256=contract.project_config_sha256,
        caption_style=evidence,
        caption_renderer="remotion",
        caption_features=["burned_in", "bold", "caption_layout_measured"],
        caption_layout=layout_evidence,
        captions_burned=True,
        brand_safe_margins=SAFE_MARGINS,
    )
    return check_brand(Path("final.mp4"), contract, manifest)


def _clean_evidence(project_font: str) -> dict:
    """Evidence from cues the chunker would actually emit under the contract."""
    layout = layout_captions(
        _cues("wziąć odpowiedzialność", "za to nikomu", "udowadniając na siłę"),
        _reference_style(),
        **REELS,
        safe_margins=SAFE_MARGINS,
        font_file=project_font,
    )
    return layout.evidence()


def test_brand_qa_passes_a_measured_layout_that_fits(project_font: str, monkeypatch) -> None:
    report = _qa_report(_clean_evidence(project_font), _reference_style(), monkeypatch)

    assert report.errors == []
    names = {check.name for check in report.checks}
    assert {
        "captions are drawn in full",
        "captions carry no added ellipsis",
        "captions fit the caption box",
        "caption cue length within the contract",
    } <= names


@pytest.mark.parametrize(
    ("change", "failing_check"),
    [
        ({"truncated_cues": [3]}, "captions are drawn in full"),
        ({"ellipsis_cues": [4]}, "captions carry no added ellipsis"),
        ({"max_line_width_px": 9999.0}, "captions fit the caption box"),
        ({"over_length_cues": [5]}, "caption cue length within the contract"),
    ],
)
def test_brand_qa_detects_each_caption_layout_defect(
    change: dict, failing_check: str, project_font: str, monkeypatch
) -> None:
    evidence = {**_clean_evidence(project_font), **change}

    report = _qa_report(evidence, _reference_style(), monkeypatch)

    assert failing_check in {check.name for check in report.errors}


def test_brand_qa_detects_a_style_that_does_not_match_the_contract(
    project_font: str, monkeypatch
) -> None:
    """The reported config problem: the contract says one size, the render used another."""
    from social_video.qa.brand import check_brand
    from social_video.schemas.brand import BrandProfile
    from social_video.schemas.config import BrandContract
    from social_video.schemas.qa import RenderManifest

    style = _reference_style()
    contract = BrandContract(
        project_config_path="c.yaml",
        project_config_sha256="d" * 64,
        project_root="/p",
        brand=BrandProfile(captions=style),
        output_width=1080,
        output_height=1920,
        output_fps="30/1",
        safe_margins=SAFE_MARGINS,
    )

    class Video:
        display_size = (1080, 1920)

    class Info:
        video = Video()

    monkeypatch.setattr("social_video.qa.brand.probe", lambda _: Info())
    drifted = style.model_dump(mode="json", exclude={"schema_version"})
    drifted["position"] = style.position.value
    drifted["font_size_pct"] = 5.0
    drifted["max_chars_per_cue"] = 32
    drifted["outline_or_shadow"] = "outline"
    report = check_brand(
        Path("final.mp4"),
        contract,
        RenderManifest(
            output="final.mp4",
            edl="main",
            rendered_at="2026-09-21T00:00:00Z",
            duration=10,
            width=1080,
            height=1920,
            frame_rate="30/1",
            brand_contract_sha256=contract.project_config_sha256,
            caption_style=drifted,
            caption_renderer="remotion",
            caption_features=["burned_in", "bold"],
            caption_layout=_clean_evidence(project_font),
            captions_burned=True,
            brand_safe_margins=SAFE_MARGINS,
        ),
    )

    failed = {check.name for check in report.errors}
    assert {"caption font size", "caption chars per cue", "caption outline or shadow"} <= failed
