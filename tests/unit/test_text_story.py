"""Text stories: a sentence per shot from the brief, nothing transcribed."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from social_video.captions.features import CAPTION_STORY, caption_features
from social_video.editorial.story import (
    compile_story,
    parse_story,
    story_plan,
    story_style,
    story_track,
)
from social_video.errors import ValidationError
from social_video.publish_template import description_template, placeholders
from social_video.qa.brand import _check_ending
from social_video.qa.reel import _story_question
from social_video.schemas.base import save_artifact
from social_video.schemas.brand import CaptionPosition, CaptionStyle
from social_video.schemas.config import BrandContract
from social_video.schemas.motion import MotionElement, MotionPlan
from social_video.schemas.plan import EditPlan, PlanItem
from social_video.schemas.qa import QAReport, RenderManifest
from social_video.schemas.source import SourceEntry, SourceManifest
from social_video.workspace.layout import Workspace
from tests.unit.test_remotion_only import _contract

STORY = """# Historia
"Jesteś na przystanku." -> przystanek.mp4
„Jest 7:30.” → zegar.mp4 @ 2.0
"A autobus znowu się spóźnia?" -> droga.mp4 @ 0,5 1.4s
notatka, nie wiersz historii
"""


def _sources() -> SourceManifest:
    def entry(name: str) -> SourceEntry:
        return SourceEntry.model_construct(id=name.split(".")[0], path=f"/m/{name}", duration=6.0)

    return SourceManifest.model_construct(
        sources=[entry("przystanek.mp4"), entry("zegar.mp4"), entry("droga.mp4")]
    )


def test_story_lines_are_parsed_with_their_in_points_and_holds() -> None:
    lines = parse_story(STORY)
    assert [line.text for line in lines] == [
        "Jesteś na przystanku.", "Jest 7:30.", "A autobus znowu się spóźnia?"
    ]  # fmt: skip
    assert (lines[1].clip, lines[1].at, lines[1].hold) == ("zegar.mp4", 2.0, None)
    assert (lines[2].at, lines[2].hold) == (0.5, 1.4)
    with pytest.raises(ValidationError, match="no story lines"):
        parse_story("tylko notatka")


def test_the_plan_holds_each_shot_for_its_sentence() -> None:
    plan = story_plan(parse_story(STORY), _sources(), cut_every=1.2)
    assert plan.mode == "text_story"
    assert [(i.source, i.start, i.end) for i in plan.items] == [
        ("przystanek", 0.0, 1.2), ("zegar", 2.0, 3.2), ("droga", 0.5, 1.9)
    ]  # fmt: skip
    with pytest.raises(ValidationError, match="cut_every"):
        story_plan(parse_story(STORY), _sources(), cut_every=3.0)
    with pytest.raises(ValidationError, match="not a source"):
        story_plan(parse_story('"Zdanie." -> brak.mp4'), _sources())


def test_a_story_item_needs_its_sentence() -> None:
    with pytest.raises(PydanticValidationError, match="story_text"):
        EditPlan(
            goal="x", mode="text_story",
            items=[PlanItem(action="keep", source="a", start=0, end=1)],
        )  # fmt: skip


def test_the_cut_is_muted_and_each_sentence_fills_its_shot() -> None:
    plan = story_plan(parse_story(STORY), _sources(), cut_every=1.2)
    edl = compile_story(plan, width=1080, height=1920)
    assert all(r.muted for r in edl.ranges)
    style = story_style(CaptionStyle(case="upper"), font_size_pct=5.0, position="center")
    track = story_track(edl, style, language="pl")
    assert [(c.start, c.end) for c in track.cues] == [(0.0, 1.2), (1.2, 2.4), (2.4, 3.8)]
    assert track.cues[0].text == "JESTEŚ NA PRZYSTANKU." and track.origin == "story"
    assert style.position is CaptionPosition.CENTER and not style.highlight_active_word
    assert CAPTION_STORY in caption_features(style, track, highlight=False)
    report = QAReport(output="x", edl="main")
    _story_question(report, track)
    assert report.checks[0].passed


def test_the_description_template_fills_only_what_exists(tmp_path: Path) -> None:
    ws = Workspace.at(tmp_path / "edit")
    ws.root.mkdir(parents=True)
    contract = _contract().model_copy(update={"share_cta": "Wyślij to komuś, kto zaczyna."})
    save_artifact(contract, ws.brand_contract)
    title = MotionElement(
        type="hook_title", start=0.4, end=3.4, text="Kto pierwszy ustąpi?", reason="Title."
    )
    save_artifact(MotionPlan(elements=[title], rationale="x"), ws.motion_plan)
    text = description_template(ws)
    assert text.startswith("# Kto pierwszy ustąpi?")
    assert "Wyślij to komuś, kto zaczyna." in text
    left = placeholders(text)
    assert any("podpis" in p for p in left) and any("2-4 zdania" in p for p in left)


def _render(**ending) -> RenderManifest:
    return RenderManifest.model_construct(ending_applied=ending)


def test_brand_qa_reads_the_ending_against_end_style() -> None:
    found: list[tuple[str, bool, bool]] = []

    def add(name: str, ok: bool, message: str, *, warning: bool = False) -> None:
        found.append((name, ok, warning))

    overlay: BrandContract = _contract().model_copy(update={"end_style": "overlay"})
    _check_ending(add, overlay, _render())
    assert found == [("ending as contracted", False, False)]
    found.clear()
    _check_ending(add, overlay, _render(overlay=True, end_card=False, cta=False, window_s=3))
    assert ("ending as contracted", True, True) in found
    found.clear()
    _check_ending(add, _contract(), _render(overlay=False, end_card=False, cta=False))
    assert found == [("something closes the reel", False, True)]
