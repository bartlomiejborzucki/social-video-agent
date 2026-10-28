"""Words not spoken yet, drawn dimmed: opt-in, Remotion only, vouched for by QA."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from social_video.captions.features import UPCOMING_WORDS_DIMMED, caption_features
from social_video.captions.fit import layout_captions
from social_video.errors import ValidationError
from social_video.pipeline import _check_remotion_only
from social_video.project_config import compile_brand_contract
from social_video.qa.brand import check_brand
from social_video.remotion import _caption_payload
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.config import CaptionConfig
from social_video.schemas.qa import RenderManifest
from social_video.schemas.workflow import Renderer
from social_video.workspace.layout import Workspace
from tests.unit.test_caption_emphasis import _track
from tests.unit.test_remotion_only import _contract


def _compiled(tmp_path: Path, captions: str = ""):
    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True)
    (project / "assets" / "Lato.ttf").write_bytes(b"fixture-font")
    config = project / "social-video.yaml"
    config.write_text(
        f"schema_version: 1\nfont_file: assets/Lato.ttf\n{captions}", encoding="utf-8"
    )
    return compile_brand_contract(config, Workspace.at(project / "edit"), project_root=project)


def test_dimming_is_opt_in_and_bounded(tmp_path: Path) -> None:
    assert CaptionConfig().upcoming_word_opacity == 1.0
    assert _compiled(tmp_path / "a").brand.captions.upcoming_word_opacity == 1.0
    dimmed = _compiled(tmp_path / "b", "caption_style:\n  upcoming_word_opacity: 0.45\n")
    assert dimmed.brand.captions.upcoming_word_opacity == 0.45
    for wrong in (0.2, 1.1):
        with pytest.raises(PydanticValidationError):
            CaptionConfig(upcoming_word_opacity=wrong)


def test_only_a_renderer_that_draws_it_records_it() -> None:
    style = CaptionStyle(upcoming_word_opacity=0.4)
    assert UPCOMING_WORDS_DIMMED in caption_features(
        style, _track(), highlight=False, animated=True
    )
    assert UPCOMING_WORDS_DIMMED not in caption_features(style, _track(), highlight=False)
    # Without word timings nothing is "to come".
    assert UPCOMING_WORDS_DIMMED not in caption_features(
        style, _track(words=False), highlight=False, animated=True
    )
    plain = CaptionStyle()
    assert UPCOMING_WORDS_DIMMED not in caption_features(
        plain, _track(), highlight=False, animated=True
    )


def test_the_ffmpeg_route_refuses_dimmed_words() -> None:
    with pytest.raises(ValidationError, match=r"upcoming_word_opacity: 0\.5"):
        _check_remotion_only(_contract(upcoming_word_opacity=0.5), Renderer.FFMPEG, captions=True)
    _check_remotion_only(_contract(upcoming_word_opacity=0.5), Renderer.REMOTION, captions=True)


def test_remotion_gets_word_times_for_dimming_alone() -> None:
    track = _track()
    style = CaptionStyle(upcoming_word_opacity=0.4, max_lines=2)
    layout = layout_captions(list(track.cues), style, width=1080, height=1920)

    payload = _caption_payload(layout, track, style, highlight=False)

    drawn = [word for line in payload[0]["lines"] for word in line["words"]]
    assert [(w["start"], w["end"]) for w in drawn] == [(0.0, 0.5), (0.5, 1.0)]
    # Without dimming (or a highlight or keywords) no word times are shipped.
    plain = _caption_payload(layout, track, CaptionStyle(max_lines=2), highlight=False)
    assert "words" not in plain[0]["lines"][0]


def test_brand_qa_fails_a_render_that_did_not_dim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Video:
        display_size = (1080, 1920)

    class Info:
        video = Video()

    monkeypatch.setattr("social_video.qa.brand.probe", lambda _: Info())
    contract = _compiled(tmp_path, "caption_style:\n  upcoming_word_opacity: 0.5\n")

    def check(features: list[str]):
        render = RenderManifest(
            output="final.mp4", edl="main", rendered_at="2026-10-28T00:00:00Z", duration=1,
            width=1080, height=1920, frame_rate="30/1",
            brand_contract_sha256=contract.project_config_sha256,
            caption_style=contract.brand.captions.model_dump(mode="json"),
            captions_burned=True, caption_renderer="remotion", caption_features=features,
            brand_safe_margins=contract.safe_margins,
        )  # fmt: skip
        checks = check_brand(tmp_path / "final.mp4", contract, render).checks
        return next(c for c in checks if c.name == "caption upcoming words dimmed")

    assert check(["burned_in", "bold", UPCOMING_WORDS_DIMMED]).passed
    failed = check(["burned_in", "bold"])
    assert not failed.passed and "did not draw it" in failed.message
