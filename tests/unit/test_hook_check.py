"""Hook check on Polish first lines: concrete fixes, never a verdict."""

from __future__ import annotations

from social_video.qa.hook import check_hook, check_text, load_words, matches
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord


def _by_name(findings):
    return {f.name: f for f in findings}


def test_a_situation_with_a_child_and_tension_passes() -> None:
    found = _by_name(check_text("Dziecko miało posprzątać, a teraz nie chce?", first_word_at=0.1))
    assert all(f.ok for f in found.values()), [f for f in found.values() if not f.ok]


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
    assert not found["konkretna sytuacja z dzieckiem"].ok
    assert "przenieś książkę" in found["bez nazwy, tytułu i książki"].fix


def test_viewer_address_counts_and_short_words_match_whole() -> None:
    words = load_words()
    assert matches("Twoje dziecko krzyczy w sklepie", words["address"]) == ["twoj", "twoje"]
    # "ci" is a word, not the start of "ciekawe".
    assert "ci" not in matches("To ciekawe", words["address"])
    assert matches("Znowu to samo", words["tension"]) == ["znowu"]


def test_the_report_is_written_and_scored(tmp_path) -> None:
    cue = CaptionCue(
        index=1, start=0.0, end=2.0, text="Przecież się dogadaliśmy!",
        words=[CaptionWord(text="Przecież", start=0.05, end=0.5)],
    )  # fmt: skip
    report = check_hook(CaptionTrack(cues=[cue]), None, analysis_dir=tmp_path)
    assert (tmp_path / "hook-check.json").is_file()
    assert report.score.endswith("/6")
    assert any("dziecka" in fix or "dziecko" in fix for fix in report.fixes)
