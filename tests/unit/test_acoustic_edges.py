"""Range edges follow the heard speech, not the transcript's word times."""

from __future__ import annotations

import numpy as np
import pytest

from social_video.analysis.speech import RATE
from social_video.editorial.acoustic import AcousticEdges
from social_video.editorial.compile import compile_plan
from social_video.profiles import load_profile
from social_video.schemas.plan import EditPlan, PlanAction, PlanItem
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing

PROFILE = load_profile("talking-head")


def _transcript(words: list[tuple[str, float, float]], duration: float = 20.0) -> Transcript:
    tokens = [TranscriptToken(type=TokenType.WORD, text=t, start=s, end=e) for t, s, e in words]
    return Transcript(
        source_id="kamera", source_fingerprint="x", duration=duration, provider="test",
        tokens=synthesize_spacing(tokens),
    )  # fmt: skip


def _signal(speech: list[tuple[float, float]], duration: float = 20.0) -> np.ndarray:
    """Room tone at -60 dBFS with voice bursts at -20 dBFS."""
    rng = np.random.default_rng(3)
    signal = rng.normal(0, 0.001, int(duration * RATE)).astype(np.float32)
    for start, end in speech:
        a, b = int(start * RATE), int(end * RATE)
        signal[a:b] += rng.normal(0, 0.1, b - a).astype(np.float32)
    return signal


def _edges(signal: np.ndarray) -> AcousticEdges:
    def load(source_id: str, start: float, end: float) -> np.ndarray:
        a = max(0, round(start * RATE))
        return signal[a : round(end * RATE)]

    return AcousticEdges(load)


def test_the_last_syllable_is_kept_when_whisper_ends_the_word_early() -> None:
    # "wieczorem": whisper says it ends at 10.66, the voice runs to 10.90.
    transcript = _transcript([("na", 9.6, 9.8), ("wieczorem.", 9.9, 10.66)])
    edges = _edges(_signal([(9.6, 9.8), (9.9, 10.9)]))
    _start, end = edges.refine(transcript, 9.5, 10.76, padding=0.1)
    assert end == pytest.approx(11.0, abs=0.02)
    assert any(s.edge == "out" and "10.90" in s.reason for s in edges.shifts)


def test_glued_silence_before_the_first_word_is_trimmed() -> None:
    # The word "starts" at 6.28; the voice starts at 6.74.
    transcript = _transcript([("Dziecko", 6.28, 7.1), ("miało", 7.15, 7.8)])
    edges = _edges(_signal([(6.74, 7.1), (7.15, 7.8)]))
    start, _end = edges.refine(transcript, 6.18, 7.9, padding=0.1)
    assert start == pytest.approx(6.64, abs=0.02)
    assert any(s.edge == "in" for s in edges.shifts)


def test_an_edge_never_crosses_into_the_next_word() -> None:
    transcript = _transcript([("tak", 3.0, 3.3), ("dalej", 3.42, 3.9)])
    # The voice under "tak" runs to 3.40, right up to the next word.
    edges = _edges(_signal([(3.0, 3.4), (3.42, 3.9)]))
    _start, end = edges.refine(transcript, 2.9, 3.35, padding=0.1)
    assert end <= 3.42 + 1e-6


def test_clean_edges_are_left_where_the_words_put_them() -> None:
    transcript = _transcript([("Mamo", 2.0, 2.5)])
    edges = _edges(_signal([(2.0, 2.5)]))
    start, end = edges.refine(transcript, 1.9, 2.6, padding=0.1)
    assert (start, end) == pytest.approx((1.9, 2.6), abs=0.02)
    assert not edges.shifts


def test_speech_past_the_end_of_the_edit_is_reported() -> None:
    transcript = _transcript([("wieczorem.", 9.9, 10.66)])
    edges = _edges(_signal([(9.9, 11.2)]))
    assert edges.check_tail(transcript, 10.7) > 0.1
    quiet = _edges(_signal([(9.9, 10.66)]))
    assert quiet.check_tail(transcript, 10.76) == 0.0


def test_compile_moves_edges_and_says_so() -> None:
    transcript = _transcript([("Zapisz", 5.0, 5.4), ("wieczorem.", 5.5, 6.16)])
    plan = EditPlan(
        goal="end",
        items=[PlanItem(action=PlanAction.KEEP, source="kamera", start=5.0, end=6.16)],
    )
    edges = _edges(_signal([(5.0, 5.4), (5.5, 6.4)]))
    edl = compile_plan(plan, transcript, PROFILE, edges=edges)
    assert edl.ranges[-1].end == pytest.approx(6.5, abs=0.02)
    assert "out +" in edl.ranges[-1].reason
    assert not edges.warnings
