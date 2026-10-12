"""Properties of accent spacing and beat snapping over generated speech."""

from __future__ import annotations

import wave
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from social_video.analysis.beats import MIN_GAP, detect_beats, onsets, snap
from social_video.motion.energy import ENERGY
from social_video.motion.suggest import find_accents
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.transcript import Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing
from tests.conftest import requires_ffmpeg

# Words that trigger every kind of accent, mixed with plain ones.
VOCAB = [
    "Trzy", "błędy", "zasięgi.", "ale", "but", "instead", "73", "12%", "procent", "razy",
    "po", "pierwsze", "drugie", "first", "second", "napisy,", "hook.", "dlaczego?",
    "why?", "działa.", "to", "nie", "wszystko.", "2024", "ogląda", "bez", "dźwięku.",
]  # fmt: skip

word = st.tuples(
    st.sampled_from(VOCAB),
    st.floats(min_value=0.02, max_value=1.6),  # gap before the word
    st.floats(min_value=0.1, max_value=0.6),  # length of the word
)


@st.composite
def speech(draw):
    """A transcript and an EDL that keeps all of it, or drops a span from it."""
    tokens: list[TranscriptToken] = []
    clock = 0.0
    for text, gap, length in draw(st.lists(word, min_size=1, max_size=80)):
        start = clock + gap
        end = round(start + length, 3)
        tokens.append(TranscriptToken(text=text, start=round(start, 3), end=end))
        clock = start + length
    duration = round(clock + 1.0, 3)
    transcript = Transcript(
        source_id="clip",
        source_fingerprint="f" * 16,
        duration=duration,
        provider="test",
        tokens=synthesize_spacing(tokens),
    )
    ranges = [EDLRange(source="clip", start=0, end=duration)]
    if duration > 4.0 and draw(st.booleans()):
        cut = draw(st.floats(min_value=1.0, max_value=duration - 3.0))
        resume = draw(st.floats(min_value=cut + 0.5, max_value=duration - 1.0))
        ranges = [
            EDLRange(source="clip", start=0, end=round(cut, 3)),
            EDLRange(source="clip", start=round(resume, 3), end=duration),
        ]
    return transcript, EDL(ranges=ranges)


@settings(max_examples=80, deadline=None)
@given(speech(), st.sampled_from(sorted(ENERGY)))
def test_accents_never_exceed_the_energy_budget(case, level: str) -> None:
    transcript, edl = case
    energy = ENERGY[level]

    found = find_accents(transcript, edl, energy).candidates

    minutes = max(edl.total_duration, 1.0) / 60.0
    accents = [c for c in found if c.transition is None]
    transitions = [c for c in found if c.transition is not None]
    assert len(accents) <= max(1, round(energy.accents_per_minute * minutes))
    assert len(transitions) <= int(energy.transitions_per_minute * minutes + 1e-9)
    times = sorted(c.at for c in accents)
    assert all(b - a >= energy.min_accent_gap - 1e-6 for a, b in pairwise(times))
    assert all(c.punch_in.scale <= energy.punch_in_max for c in accents if c.punch_in is not None)
    assert all(0.0 <= c.at <= edl.total_duration for c in found)
    assert [c.at for c in found] == sorted(c.at for c in found)
    assert [c.id for c in found] == [f"acc-{n:03d}" for n in range(1, len(found) + 1)]


@settings(max_examples=60, deadline=None)
@given(speech(), st.lists(st.floats(min_value=0.0, max_value=60.0), max_size=40))
def test_beats_move_only_punch_ins_and_only_a_little(case, beats: list[float]) -> None:
    transcript, edl = case
    energy = ENERGY["bold"]
    beats = sorted(round(b, 3) for b in beats)

    plain = find_accents(transcript, edl, energy).candidates
    snapped = find_accents(transcript, edl, energy, beats=beats).candidates

    assert len(snapped) == len(plain)
    assert sorted(c.transition.at for c in snapped if c.transition) == sorted(
        c.transition.at for c in plain if c.transition
    )
    assert sorted(c.element.start for c in snapped if c.element) == sorted(
        c.element.start for c in plain if c.element
    )
    before = [(c.punch_in.start, c.punch_in.end) for c in plain if c.punch_in]
    for candidate in (c for c in snapped if c.punch_in):
        start, end = candidate.punch_in.start, candidate.punch_in.end
        assert candidate.at == start
        # Moved by at most the snap tolerance, onto a beat or not at all, and
        # held for exactly as long as before.
        assert any(
            abs(start - s) <= 0.12 + 1e-6
            and abs((end - start) - (e - s)) <= 2e-3
            and (start == s or start in beats)
            for s, e in before
        ), (start, end, before)


@given(st.floats(min_value=0, max_value=100), st.lists(st.floats(0, 100), max_size=30))
def test_snap_returns_the_time_or_a_beat_within_tolerance(time: float, beats: list[float]) -> None:
    snapped = snap(time, beats)

    assert snapped == time or (snapped in beats and abs(snapped - time) <= 0.12)


def _click_track(bpm: float, seconds: float, rate: int = 11025, *, noise: float = 0.005):
    rng = np.random.default_rng(7)
    signal = (rng.standard_normal(int(seconds * rate)) * noise).astype(np.float32)
    clicks = list(np.arange(0.5, seconds - 0.3, 60.0 / bpm))
    for at in clicks:
        start = int(at * rate)
        signal[start : start + 200] += (np.hanning(200) * 0.9).astype(np.float32)
    return signal, clicks


@pytest.mark.parametrize("bpm", [90, 120, 150])
def test_onsets_find_every_click_of_a_steady_tempo_and_nothing_else(bpm: int) -> None:
    signal, clicks = _click_track(bpm, 8.0)

    beats = onsets(signal, 11025)

    for expected in clicks:
        assert any(abs(b - expected) < 0.05 for b in beats), (expected, beats)
    for found in beats:
        assert any(abs(found - c) < 0.05 for c in clicks), (found, clicks)
    assert all(b - a >= MIN_GAP - 1e-6 for a, b in pairwise(beats))


@requires_ffmpeg
def test_detect_beats_reads_a_file_from_an_offset(tmp_path: Path) -> None:
    signal, clicks = _click_track(120, 6.0, 44100)
    path = tmp_path / "bed.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(44100)
        out.writeframes((np.clip(signal, -1, 1) * 32767).astype("<i2").tobytes())

    beats = detect_beats(path, start_at=2.0, duration=3.0)

    expected = [c - 2.0 for c in clicks if 2.05 <= c <= 4.8]
    assert expected
    for at in expected:
        assert any(abs(b - at) < 0.06 for b in beats), (at, beats)
