"""Phrase captions: cut where the sentence breaks, never lit word by word."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from social_video.captions.chunk import build_caption_track, step_number
from social_video.captions.features import (
    CAPTION_MODE_PHRASE,
    OUTLINE_WIDTH,
    STEP_NUMBERS,
    caption_features,
)
from social_video.edl.timeline import Timeline
from social_video.project_config import compile_brand_contract
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.config import CaptionConfig
from social_video.schemas.edl import EDL, EDLRange
from social_video.workspace.layout import Workspace
from tests.unit.test_captions import make_transcript


def _timeline() -> Timeline:
    return Timeline(EDL(ranges=[EDLRange(source="a", start=0.0, end=30.0)]))


def _spoken(text: str, step: float = 0.3):
    words = text.split()
    return make_transcript([(w, i * step, i * step + step - 0.02) for i, w in enumerate(words)])


def test_karaoke_stays_the_default() -> None:
    assert CaptionConfig().mode == "karaoke"
    track = build_caption_track(_spoken("Raz dwa trzy cztery pięć sześć."), _timeline())
    assert track.mode == "karaoke"


def test_a_phrase_cue_breaks_before_a_conjunction() -> None:
    style = CaptionStyle(mode="phrase", max_words_per_cue=6, max_chars_per_cue=40)
    track = build_caption_track(
        _spoken("Mama nalała mleka do kubka bo dziecko chciało pić."), _timeline(), style=style
    )
    texts = [c.text for c in track.cues]
    assert texts[0] == "Mama nalała mleka do kubka"
    assert texts[1].startswith("bo ")
    assert track.mode == "phrase"


def test_a_phrase_cue_breaks_at_any_comma_and_stays_short() -> None:
    style = CaptionStyle(mode="phrase", max_words_per_cue=6, max_chars_per_cue=40)
    track = build_caption_track(
        _spoken("Wieczorem po kolacji, przed snem czytamy."), _timeline(), style=style
    )
    assert track.cues[0].text == "Wieczorem po kolacji,"
    karaoke = build_caption_track(
        _spoken("Wieczorem po kolacji, przed snem czytamy."),
        _timeline(),
        style=CaptionStyle(max_words_per_cue=8, max_chars_per_cue=40),
    )
    # By word count, a clause this short does not end the cue.
    assert karaoke.cues[0].text != "Wieczorem po kolacji,"
    slow = build_caption_track(
        _spoken("Bardzo powoli mówione słowa tutaj", step=0.9), _timeline(), style=style
    )
    assert all(c.end - c.start <= 2.5 + 0.1 for c in slow.cues)


def test_step_numbers_go_in_front_of_a_step() -> None:
    assert step_number("Po drugie, kolacja", "pl") == 2
    assert step_number("Krok 3 to kąpiel", "pl") == 3
    assert step_number("Drugie śniadanie", "pl") is None
    style = CaptionStyle(mode="phrase", step_numbers=True, max_chars_per_cue=40)
    track = build_caption_track(
        _spoken("Po pierwsze, kolacja. Po drugie, kąpiel."), _timeline(), style=style
    )
    texts = [c.text for c in track.cues]
    assert texts[0].startswith("1. Po pierwsze")
    assert any(t.startswith("2. Po drugie") for t in texts)
    assert track.cues[0].words[0].text == "1. Po"


def test_phrase_captions_refuse_a_word_highlight() -> None:
    with pytest.raises(PydanticValidationError, match="not lit word by word"):
        CaptionConfig(mode="phrase", active_word_highlight=True)
    with pytest.raises(PydanticValidationError, match="whole phrase"):
        CaptionConfig(mode="phrase", upcoming_word_opacity=0.5)


def test_the_track_records_what_the_renderer_reports() -> None:
    style = CaptionStyle(mode="phrase", step_numbers=True, outline_width_pct=8, outline_width=6)
    track = build_caption_track(_spoken("Po pierwsze, kolacja."), _timeline(), style=style)
    applied = caption_features(style, track, highlight=False)
    assert {CAPTION_MODE_PHRASE, STEP_NUMBERS, OUTLINE_WIDTH} <= set(applied)
    karaoke = build_caption_track(_spoken("Raz dwa."), _timeline())
    assert CAPTION_MODE_PHRASE not in caption_features(CaptionStyle(), karaoke, highlight=False)


def test_the_outline_is_a_share_of_the_font(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True)
    (project / "assets" / "Lato.ttf").write_bytes(b"fixture-font")
    config = project / "social-video.yaml"
    config.write_text(
        "schema_version: 1\nfont_file: assets/Lato.ttf\ncaption_style:\n"
        "  mode: phrase\n  case: upper\n  outline_or_shadow: outline\n"
        "  outline_width_pct: 10\n  font_size_pct: 4.0\n",
        encoding="utf-8",
    )
    contract = compile_brand_contract(config, Workspace.at(project / "edit"), project_root=project)
    style = contract.brand.captions
    assert style.mode == "phrase"
    # 4 % of 1920 is 76.8 px; a tenth of it.
    assert style.outline_width == pytest.approx(7.7, abs=0.05)
    assert style.outline_width_pct == 10


def test_a_step_number_does_not_hide_the_word_from_anchors() -> None:
    from social_video.motion.anchors import word_times

    style = CaptionStyle(mode="phrase", step_numbers=True, max_chars_per_cue=40)
    track = build_caption_track(_spoken("Krok 1 kolacja. Krok 2 kąpiel."), _timeline(), style=style)
    assert track.cues[0].text.startswith("1. Krok")
    assert [k for k, _s, _e in word_times(track)].count("krok") == 2


def test_reel_check_measures_what_is_said_after_the_opening_cue() -> None:
    from social_video.qa.reel import _phrase_cues
    from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
    from social_video.schemas.qa import QAReport

    def cue(index: int, start: float, end: float, said: float) -> CaptionCue:
        words = [CaptionWord(text="a", start=start, end=start + said)]
        return CaptionCue(index=index, start=start, end=end, text="a", words=words)

    # The opening cue is long by rule; the second is held through a pause.
    track = CaptionTrack(mode="phrase", cues=[cue(1, 0.0, 3.4, 3.4), cue(2, 3.5, 7.0, 1.2)])
    report = QAReport(output="x", edl="main")
    _phrase_cues(report, track)
    assert report.checks[0].passed
