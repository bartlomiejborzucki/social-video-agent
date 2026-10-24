"""Hook check on Polish first lines: concrete fixes, never a verdict."""

from __future__ import annotations

from pathlib import Path

from social_video.qa.hook import (
    PROJECT_WORDS,
    check_hook,
    check_text,
    load_words,
    matches,
    project_words,
)
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord


def _by_name(findings):
    return {f.name: f for f in findings}


def _project(tmp_path: Path, text: str) -> Path:
    path = tmp_path / PROJECT_WORDS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return tmp_path


def test_a_situation_from_the_project_and_tension_passes(tmp_path: Path) -> None:
    words = project_words(_project(tmp_path, "situation:\n  - kaw\n  - mlek\n"))
    found = _by_name(
        check_text("Kawa miała być gotowa, a teraz brak mleka?", first_word_at=0.1, words=words)
    )
    assert found["konkretna sytuacja"].ok
    assert all(f.ok for f in found.values()), [f for f in found.values() if not f.ok]


def test_without_project_words_the_situation_is_not_judged() -> None:
    assert load_words()["situation"] == []
    found = _by_name(check_text("Kawa miała być gotowa?", first_word_at=0.1))
    assert "konkretna sytuacja" not in found


def test_a_pre_2_7_child_list_still_counts_as_the_situation(tmp_path: Path) -> None:
    words = project_words(_project(tmp_path, "child:\n  - rower\n"))
    assert words["situation"] == ["rower"]
    assert words["address"]  # categories the project leaves out stay general


def test_a_book_title_greeting_and_slow_start_each_get_a_fix() -> None:
    found = _by_name(
        check_text(
            "Cześć kochani, dzisiaj opowiem wam o mojej nowej książce",
            first_word_at=0.8,
        )
    )
    assert not found["bez powitania"].ok
    assert not found["bez nazwy, tytułu i książki"].ok
    assert not found["co najwyżej 8 słów"].ok
    assert not found["pierwsze słowo od razu"].ok
    assert "przenieś książkę" in found["bez nazwy, tytułu i książki"].fix


def test_viewer_address_counts_and_short_words_match_whole() -> None:
    words = load_words()
    assert matches("Twoje plany na weekend", words["address"]) == ["twoj", "twoje"]
    # "ci" is a word, not the start of "ciekawe".
    assert "ci" not in matches("To ciekawe", words["address"])
    assert matches("Znowu to samo", words["tension"]) == ["znowu"]


def test_the_report_is_written_and_scored(tmp_path: Path) -> None:
    cue = CaptionCue(
        index=1, start=0.0, end=2.0, text="Przecież się umówiliśmy!",
        words=[CaptionWord(text="Przecież", start=0.05, end=0.5)],
    )  # fmt: skip
    words = project_words(_project(tmp_path, "situation:\n  - rower\n"))
    report = check_hook(CaptionTrack(cues=[cue]), None, analysis_dir=tmp_path, words=words)
    assert (tmp_path / "hook-check.json").is_file()
    assert report.score.endswith("/6")
    assert any("kto co robi" in fix for fix in report.fixes)
