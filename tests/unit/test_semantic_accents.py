"""`motion suggest` finds what the words mean: a habit replaced, a quote, stages, icons."""

from __future__ import annotations

from pathlib import Path

import pytest

from social_video.motion.anchors import anchor_to_words
from social_video.motion.energy import energy_preset
from social_video.motion.icons import IconDictionary
from social_video.motion.semantic import load_accent_words
from social_video.motion.suggest import accept_accents, find_accents
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import AccentKind, MotionElementType
from tests.unit.test_motion_energy import _transcript


def _words(line: str, start: float = 1.0, step: float = 0.4) -> list[tuple[str, float, float]]:
    return [
        (word, round(start + n * step, 3), round(start + n * step + step * 0.9, 3))
        for n, word in enumerate(line.split())
    ]


def _find(line: str, duration: float = 20.0, **options):
    spoken = _words(line)
    transcript = _transcript(spoken, duration)
    edl = EDL(ranges=[EDLRange(source="clip", start=0, end=duration)])
    options.setdefault("content_first", True)
    found = find_accents(transcript, edl, energy_preset("bold"), **options)
    return {c.kind: c for c in found.candidates}, spoken, found


def _track(spoken: list[tuple[str, float, float]]) -> CaptionTrack:
    words = [CaptionWord(text=w, start=s, end=e) for w, s, e in spoken]
    return CaptionTrack(
        cues=[CaptionCue(index=1, start=words[0].start, end=words[-1].end, text="x", words=words)]
    )


def test_instead_of_x_say_y_is_crossed_out_and_replaced_on_its_words() -> None:
    by_kind, spoken, _ = _find("Zamiast nie płacz, powiedz widzę, że ci smutno.")
    strike = by_kind[AccentKind.REPLACEMENT].element
    assert strike is not None and strike.type is MotionElementType.STRIKE
    assert (strike.text, strike.replacement) == ("Nie płacz", "Widzę, że ci smutno")
    assert (strike.at_word, strike.replace_at_word) == ("powiedz", "widzę")
    times = dict((w.strip(",."), s) for w, s, _e in spoken)
    assert strike.strike_at == pytest.approx(times["powiedz"])
    assert strike.replace_at == pytest.approx(times["widzę"])
    # Accepted and anchored to the captions, it stays where suggest put it.
    _, _, found = _find("Zamiast nie płacz, powiedz widzę, że ci smutno.")
    chosen = [c.id for c in found.candidates if c.kind is AccentKind.REPLACEMENT]
    plan, _skipped = accept_accents(None, found, chosen)
    anchored, _ = anchor_to_words(plan, _track(spoken))
    assert anchored.elements[0].strike_at == pytest.approx(strike.strike_at)


def test_better_after_a_habit_takes_the_sentence_before() -> None:
    by_kind, _, _ = _find("Nie wolno tak. Lepiej powiedz: zrobimy to razem.")
    strike = by_kind[AccentKind.REPLACEMENT].element
    assert strike is not None
    assert (strike.text, strike.replacement) == ("Nie wolno tak", "Zrobimy to razem")


def test_dont_say_without_what_to_say_instead_is_not_a_strike() -> None:
    by_kind, _, _ = _find("Nie mów tak do dziecka. To boli.")
    assert AccentKind.REPLACEMENT not in by_kind


def test_a_line_after_a_verb_of_speech_becomes_a_speech_bubble() -> None:
    by_kind, _, _ = _find("Wtedy córka mówi: jeszcze jedna bajka! I co dalej?")
    bubble = by_kind[AccentKind.QUOTE].element
    assert bubble is not None and bubble.type is MotionElementType.BUBBLE
    assert bubble.text == "Jeszcze jedna bajka!"
    assert bubble.at_word == "jeszcze" and bubble.start >= 0.3
    reported, _, _ = _find("Syn mówi, że jest jeszcze za wcześnie.")
    assert reported[AccentKind.QUOTE].element.text == "Jest jeszcze za wcześnie"
    # A verb of speech on its own is no quote.
    assert AccentKind.QUOTE not in _find("Dziecko krzyczy coraz głośniej.")[0]


def test_a_line_the_brief_quotes_becomes_a_bubble_where_it_is_said() -> None:
    by_kind, _, _ = _find(
        "Dziecko krzyczy coraz głośniej i nie chce wyjść.", quotes=["nie chce wyjść"]
    )
    bubble = by_kind[AccentKind.QUOTE].element
    assert bubble is not None and bubble.text == "Nie chce wyjść"


def test_first_then_finally_becomes_a_process_bar_anchored_to_each_stage() -> None:
    by_kind, spoken, _ = _find("Najpierw kolacja, potem kąpiel, a na koniec bajka i sen.")
    process = by_kind[AccentKind.SEQUENCE].element
    assert process is not None and process.type is MotionElementType.PROCESS
    assert process.items == ["kolacja", "kąpiel", "bajka"]
    assert [a.word for a in process.item_at_words or []] == ["kolacja", "kąpiel", "bajka"]
    times = {w.strip(",."): s for w, s, _e in spoken}
    assert process.item_times == pytest.approx([times["kolacja"], times["kąpiel"], times["bajka"]])


def test_words_from_the_icon_dictionary_get_their_icon_once() -> None:
    icons = IconDictionary(icons={"kąpiel": "bath", "bajka": "book"})
    _, _, found = _find("Po kąpieli czytamy bajkę, potem znowu kąpiel.", icons=icons)
    proposed = [c.element for c in found.candidates if c.kind is AccentKind.ICON]
    # Spaced like every accent; the bath is the first and is proposed once.
    assert [e.icon for e in proposed if e].count("bath") == 1
    assert proposed[0] is not None and proposed[0].at_word == "kąpieli"
    assert all(e is not None and 0.6 <= e.end - e.start <= 1.2 for e in proposed)
    # Calm allows no icon, so none is proposed there.
    transcript = _transcript(_words("Po kąpieli czytamy bajkę."), 20.0)
    edl = EDL(ranges=[EDLRange(source="clip", start=0, end=20.0)])
    calm = find_accents(transcript, edl, energy_preset("calm"), icons=icons)
    assert not any(c.kind is AccentKind.ICON for c in calm.candidates)


def test_a_sensitive_reel_gets_none_of_them() -> None:
    icons = IconDictionary(icons={"kąpiel": "bath"})
    by_kind, _, _ = _find(
        "Zamiast płacz powiedz smutno. Najpierw kąpiel, potem sen.", icons=icons, sensitive=True
    )
    semantic = {AccentKind.REPLACEMENT, AccentKind.QUOTE, AccentKind.SEQUENCE, AccentKind.ICON}
    assert not semantic & set(by_kind)


def test_a_project_replaces_a_category_of_words(tmp_path: Path) -> None:
    (tmp_path / ".social-video").mkdir()
    (tmp_path / ".social-video" / "accent-words.yaml").write_text(
        "quote_verbs: [szepcze]\n", encoding="utf-8"
    )
    words = load_accent_words(tmp_path)
    assert words.quote_verbs == (("szepcze",),)
    assert ("zamiast",) in words.replace_from  # the other categories stay
    by_kind, _, _ = _find("Córka szepcze: jeszcze minutka.", accent_words=words)
    assert by_kind[AccentKind.QUOTE].element.text == "Jeszcze minutka"
    (tmp_path / ".social-video" / "accent-words.yaml").write_text(
        "cytaty: [mówi]\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unknown categories cytaty"):
        load_accent_words(tmp_path)


def test_the_cli_reads_quotes_from_the_brief_and_a_sensitive_plan(tmp_path: Path) -> None:
    from social_video.cli.motion import _semantic_inputs
    from social_video.schemas.base import save_artifact
    from social_video.schemas.brief import Brief, BriefRow
    from social_video.schemas.motion import MotionPlan
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    save_artifact(
        Brief(rows=[BriefRow(start=0, end=2, said="Mama mówi „chodź już”, a ono nic."),
                    BriefRow(start=2, end=4, said="Jeszcze pięć minut!", voice_off_screen=True)]),
        ws.brief,
    )  # fmt: skip
    _words, icons, quotes, tender = _semantic_inputs(ws)
    assert quotes == ["chodź już", "Jeszcze pięć minut!"]
    assert icons is None and tender is False
    save_artifact(MotionPlan(rationale="r", sensitive_topic=True), ws.motion_plan)
    assert _semantic_inputs(ws)[3] is True
