"""A/V sync against the base render, measured on synthetic signals."""

from __future__ import annotations

import numpy as np
import pytest

from social_video.qa.av_sync import (
    HOP,
    RATE,
    SyncMeasurement,
    envelope_lag,
    envelope_of,
    frame_offset,
    sync_check,
    usable_frames,
)


def _speechlike(seconds: float, seed: int = 7) -> np.ndarray:
    """Bursts of noise with irregular gaps, like syllables."""
    rng = np.random.default_rng(seed)
    signal = np.zeros(int(seconds * RATE), dtype=np.float32)
    t = 0.0
    while t < seconds - 0.4:
        length = rng.uniform(0.08, 0.3)
        start = int(t * RATE)
        end = int((t + length) * RATE)
        signal[start:end] = rng.normal(0, rng.uniform(0.1, 0.5), end - start)
        t += length + rng.uniform(0.05, 0.4)
    return signal


@pytest.mark.parametrize("delay_ms", [0, 45, -30, 40])
def test_envelope_lag_finds_a_delay_to_five_milliseconds(delay_ms: int) -> None:
    base = _speechlike(24.0)
    shift = int(delay_ms / 1000 * RATE)
    delayed = np.roll(base, shift)
    lag = envelope_lag(envelope_of(base), envelope_of(delayed))
    assert lag == pytest.approx(delay_ms / 1000, abs=HOP / RATE)


def test_frame_offset_finds_the_shift_and_prefers_zero_on_a_tie() -> None:
    rng = np.random.default_rng(1)
    frames = rng.integers(0, 255, size=(80, 8, 8), dtype=np.uint8)
    shifted = np.roll(frames, 2, axis=0)
    usable = usable_frames(80, 30.0, [])
    assert frame_offset(frames, shifted, usable=usable) == 2
    assert frame_offset(frames, frames, usable=usable) == 0
    still = np.zeros((80, 8, 8), dtype=np.uint8)
    assert frame_offset(still, still, usable=usable) == 0


def test_usable_frames_skip_busy_spans() -> None:
    usable = usable_frames(300, 30.0, [(2.0, 4.0)], step=1)
    assert all(not (1.8 <= i / 30 <= 4.2) for i in usable)
    assert usable


def test_sync_check_fails_beyond_twenty_milliseconds() -> None:
    late = sync_check(SyncMeasurement(0.045, 0, 1 / 30))
    assert not late.passed
    assert "+45 ms" in late.message
    together = sync_check(SyncMeasurement(1 / 30, 1, 1 / 30))
    assert together.passed
    assert together.measured == pytest.approx(0.0, abs=1e-6)


def test_a_steady_tone_is_not_evidence_of_any_offset() -> None:
    t = np.arange(int(20 * RATE)) / RATE
    tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    assert envelope_lag(envelope_of(tone), envelope_of(np.roll(tone, 2000))) is None
    check = sync_check(SyncMeasurement(None, 0, 1 / 30))
    assert check.passed and "not measured" in check.message
