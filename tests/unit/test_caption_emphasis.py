"""Brand keywords and the active-word highlight, from project config to pixels."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from social_video.captions.ass import render_ass
from social_video.captions.emphasis import emphasis_keys, is_emphasised, normalise
from social_video.captions.features import KEYWORD_EMPHASIS, caption_features
from social_video.captions.fit import layout_captions
from social_video.project_config import compile_brand_contract
from social_video.qa.brand import check_brand
from social_video.remotion import _caption_payload
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.config import CaptionConfig
from social_video.schemas.qa import RenderManifest
from social_video.workspace.layout import Workspace


def _track(*, words: bool = True) -> CaptionTrack:
    return CaptionTrack(
        cues=[
            CaptionCue(
                index=1,
                start=0.0,
                end=1.0,
                text="Studio, witaj",
                words=[
                    CaptionWord(text="Studio,", start=0.0, end=0.5),
                    CaptionWord(text="witaj", start=0.5, end=1.0),
                ]
                if words
                else [],
            )
        ]
    )


@pytest.mark.parametrize(
    ("spoken", "configured", "matches"),
    [
        ("Studio,", "studio", True),
        ("„STUDIO”", "Studio", True),
        ("Studia", "Studio", False),
        ("Łódź!", "łódź", True),
        ("...", "...", False),
    ],
)
def test_matching_ignores_case_and_edge_punctuation_only(
    spoken: str, configured: str, matches: bool
) -> None:
    assert is_emphasised(spoken, emphasis_keys([configured])) is matches


def test_normalising_keeps_inner_punctuation() -> None:
    assert normalise("(e-mail)") == "e-mail"


def test_config_rejects_phrases_and_drops_duplicates() -> None:
    assert CaptionConfig(emphasis_words=[" Studio ", "Studio", "5G"]).emphasis_words == [
        "Studio",
        "5G",
    ]
    with pytest.raises(PydanticValidationError, match="single words"):
        CaptionConfig(emphasis_words=["Studio Bell Labs"])
    with pytest.raises(PydanticValidationError, match="#RRGGBB"):
        CaptionConfig(emphasis_color="yellow")


def test_project_config_compiles_highlight_and_emphasis(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True)
    (project / "assets" / "Lato.ttf").write_bytes(b"fixture-font")
    config = project / "social-video.yaml"
    config.write_text(
        """schema_version: 1
font: Lato
font_file: assets/Lato.ttf
caption_style:
  active_word_highlight: true
  highlight_color: "#00FF88"
  emphasis_words: [Studio, 5G]
  emphasis_color: "#28bca5"
""",
        encoding="utf-8",
    )

    style = compile_brand_contract(
        config, Workspace.at(project / "edit"), project_root=project
    ).brand.captions

    assert style.highlight_active_word
    assert style.highlight_colour == "#00FF88"
    assert style.emphasis_words == ["Studio", "5G"]
    assert style.emphasis_colour == "#28BCA5"


def test_ass_colours_a_keyword_without_a_highlight() -> None:
    style = CaptionStyle(emphasis_words=["studio"], emphasis_colour="#28BCA5")

    dialogue = render_ass(_track(), style, width=1080, height=1920).splitlines()[-1]

    assert dialogue.endswith("{\\1c&H00A5BC28}Studio,{\\1c&H00FFFFFF} witaj")


def test_ass_keeps_a_keyword_emphasised_between_highlights() -> None:
    style = CaptionStyle(
        emphasis_words=["studio"], emphasis_colour="#28BCA5", highlight_active_word=True
    )

    dialogue = render_ass(_track(), style, width=1080, height=1920).splitlines()[-1]

    # The keyword rests in its colour and returns to it, not to plain white.
    assert "{\\1c&H00A5BC28\\t(0,1,\\1c&H0000D4FF)\\t(500,501,\\1c&H00A5BC28)}Studio," in dialogue
    assert "{\\1c&H00FFFFFF\\t(500,501,\\1c&H0000D4FF)" in dialogue


def test_emphasis_is_recorded_as_drawn_and_checked_by_brand_qa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    style = CaptionStyle(emphasis_words=["studio"])
    assert KEYWORD_EMPHASIS in caption_features(style, _track(), highlight=False)

    class Video:
        display_size = (1080, 1920)

    class Info:
        video = Video()

    monkeypatch.setattr("social_video.qa.brand.probe", lambda _: Info())
    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True)
    (project / "assets" / "Lato.ttf").write_bytes(b"fixture-font")
    config = project / "social-video.yaml"
    config.write_text(
        "schema_version: 1\nfont_file: assets/Lato.ttf\n"
        "caption_style:\n  emphasis_words: [Studio]\n",
        encoding="utf-8",
    )
    contract = compile_brand_contract(config, Workspace.at(project / "edit"), project_root=project)

    def report(features: list[str]):
        render = RenderManifest(
            output="final.mp4",
            edl="main",
            rendered_at="2026-09-23T00:00:00Z",
            duration=1,
            width=1080,
            height=1920,
            frame_rate="30/1",
            brand_contract_sha256=contract.project_config_sha256,
            caption_style=contract.brand.captions.model_dump(mode="json"),
            captions_burned=True,
            caption_renderer="ffmpeg-ass",
            caption_features=features,
            brand_safe_margins=contract.safe_margins,
        )
        checks = check_brand(tmp_path / "final.mp4", contract, render).checks
        return next(check for check in checks if check.name == "caption keyword emphasis")

    assert report(["burned_in", KEYWORD_EMPHASIS]).passed
    assert not report(["burned_in"]).passed


@pytest.mark.parametrize("words", [True, False])
def test_remotion_receives_emphasis_with_or_without_word_timings(words: bool) -> None:
    track = _track(words=words)
    style = CaptionStyle(emphasis_words=["studio"], max_lines=2)
    layout = layout_captions(list(track.cues), style, width=1080, height=1920)

    payload = _caption_payload(layout, track, style, highlight=False)

    drawn = [word for line in payload[0]["lines"] for word in line["words"]]
    assert [word["emphasis"] for word in drawn] == [True, False]
    # With no highlight, no word is ever timed as active.
    assert all(word["start"] > word["end"] for word in drawn)
