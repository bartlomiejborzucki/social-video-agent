"""Tests for crop smoothing.

The three properties that make reframing look deliberate: it does not lag
behind sustained movement, it rejects detection noise, and it holds completely
still for movement inside the dead zone.
"""

from __future__ import annotations

import random
import statistics

from social_video.reframe.smooth import (
    SmoothingConfig,
    choose_with_hysteresis,
    dedupe_keyframes,
    smooth_positions,
)

NO_DEAD_ZONE = SmoothingConfig(dead_zone=0.0, alpha=0.25)


class TestSmoothPositions:
    def test_empty_and_single(self):
        assert smooth_positions([], span=100) == []
        assert smooth_positions([5.0], span=100) == [5.0]

    def test_does_not_lag_behind_sustained_movement(self):
        # A one-directional filter leaves a permanent offset on a constant
        # velocity move; the zero-phase filter must not.
        ramp = [float(i * 20) for i in range(20)]
        out = smooth_positions(ramp, span=400, config=NO_DEAD_ZONE)
        for index in (0, len(ramp) // 2, -1):
            assert abs(ramp[index] - out[index]) < 5.0

    def test_rejects_noise(self):
        random.seed(1)
        noisy = [100 + random.uniform(-40, 40) for _ in range(30)]
        out = smooth_positions(noisy, span=400, config=NO_DEAD_ZONE)
        assert statistics.pstdev(out) < statistics.pstdev(noisy) / 4
        # Smoothing must not shift the series.
        assert abs(statistics.mean(out) - statistics.mean(noisy)) < 5.0

    def test_dead_zone_holds_completely_still(self):
        random.seed(2)
        jitter = [200 + random.uniform(-5, 5) for _ in range(40)]
        out = smooth_positions(jitter, span=400, config=SmoothingConfig(dead_zone=0.2))
        assert len(set(out)) == 1, "small jitter must not move the frame at all"

    def test_follows_movement_beyond_the_dead_zone(self):
        series = [0.0] * 10 + [300.0] * 10
        out = smooth_positions(series, span=400, config=SmoothingConfig(dead_zone=0.05))
        assert out[-1] > 200.0


class TestDedupeKeyframes:
    def test_drops_keyframes_inside_the_dead_zone(self):
        times = [0.0, 1.0, 2.0, 3.0]
        positions = [100.0, 101.0, 102.0, 400.0]
        kept = dedupe_keyframes(times, positions, span=400, dead_zone=0.04)
        assert [t for t, _ in kept] == [0.0, 3.0]

    def test_keeps_the_first_keyframe(self):
        kept = dedupe_keyframes([0.0], [7.0], span=400)
        assert kept == [(0.0, 7.0)]

    def test_empty(self):
        assert dedupe_keyframes([], [], span=400) == []


class TestHysteresis:
    def test_does_not_switch_on_a_marginal_lead(self):
        # Subject 1 leads slightly at every step; the crop must stay on 0.
        scores = [[1.0, 0.9], [0.9, 1.0], [1.0, 0.95], [0.95, 1.0]]
        assert choose_with_hysteresis(scores, hysteresis=0.25) == [0, 0, 0, 0]

    def test_switches_on_a_clear_lead(self):
        scores = [[1.0, 0.1], [0.1, 1.0], [0.1, 1.0]]
        assert choose_with_hysteresis(scores, hysteresis=0.25) == [0, 1, 1]

    def test_handles_steps_with_no_candidates(self):
        assert choose_with_hysteresis([[1.0, 0.1], [], [0.1, 1.0]]) == [0, 0, 1]
