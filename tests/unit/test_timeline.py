"""Tests for source<->output time mapping.

Getting this wrong is what makes captions drift further out of sync with every
cut, so the interval mapping across a splice is tested explicitly.
"""

from __future__ import annotations

import pytest

from social_video.edl.timeline import Timeline
from social_video.schemas.edl import EDL, EDLRange


def edl_with(*ranges: tuple[float, float], speed: float = 1.0) -> EDL:
    return EDL(ranges=[EDLRange(source="a", start=s, end=e, speed=speed) for s, e in ranges])


class TestTimeline:
    def test_single_range_starts_at_zero(self):
        tl = Timeline(edl_with((10.0, 15.0)))
        assert tl.duration == pytest.approx(5.0)
        assert tl.slices[0].output_start == 0.0

    def test_ranges_are_laid_end_to_end(self):
        tl = Timeline(edl_with((10.0, 12.0), (30.0, 33.0)))
        assert tl.duration == pytest.approx(5.0)
        assert tl.slices[1].output_start == pytest.approx(2.0)

    def test_cut_boundaries_exclude_the_start(self):
        tl = Timeline(edl_with((0.0, 2.0), (5.0, 7.0), (9.0, 10.0)))
        assert tl.cut_boundaries() == pytest.approx([2.0, 4.0])

    def test_maps_source_time_into_output(self):
        tl = Timeline(edl_with((10.0, 12.0), (30.0, 33.0)))
        # 31s of source is 1s into the second range, which starts at output 2s.
        assert tl.map_to_output("a", 31.0) == pytest.approx([3.0])

    def test_removed_material_maps_nowhere(self):
        tl = Timeline(edl_with((10.0, 12.0), (30.0, 33.0)))
        assert tl.map_to_output("a", 20.0) == []

    def test_material_used_twice_maps_twice(self):
        tl = Timeline(edl_with((0.0, 5.0), (0.0, 5.0)))
        assert tl.map_to_output("a", 1.0) == pytest.approx([1.0, 6.0])

    def test_interval_straddling_a_cut_is_split(self):
        # A word spanning 11.5-30.5 survives only as its two kept halves.
        tl = Timeline(edl_with((10.0, 12.0), (30.0, 33.0)))
        pieces = tl.map_interval("a", 11.5, 30.5)
        assert len(pieces) == 2
        assert pieces[0] == pytest.approx((1.5, 2.0))
        assert pieces[1] == pytest.approx((2.0, 2.5))

    def test_interval_entirely_cut_yields_nothing(self):
        tl = Timeline(edl_with((10.0, 12.0), (30.0, 33.0)))
        assert tl.map_interval("a", 20.0, 25.0) == []

    def test_other_sources_are_ignored(self):
        tl = Timeline(edl_with((0.0, 5.0)))
        assert tl.map_interval("b", 1.0, 2.0) == []

    def test_speed_change_compresses_output_time(self):
        tl = Timeline(edl_with((0.0, 10.0), speed=2.0))
        assert tl.duration == pytest.approx(5.0)
        assert tl.map_to_output("a", 10.0) == pytest.approx([5.0])

    def test_round_trip_source_to_output_and_back(self):
        tl = Timeline(edl_with((10.0, 12.0), (30.0, 33.0)))
        sl = tl.slices[1]
        assert sl.to_source(sl.to_output(31.0)) == pytest.approx(31.0)
