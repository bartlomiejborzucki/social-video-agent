"""Mapping between source time and output time.

Captions, overlays, and QA findings are all authored against one of the two and
consumed against the other. Getting this mapping wrong is the classic cause of
captions that drift further out of sync with every cut.
"""

from __future__ import annotations

from dataclasses import dataclass

from social_video.schemas.edl import EDL, EDLRange


@dataclass(frozen=True)
class TimelineSlice:
    """One EDL range, placed on the output timeline."""

    index: int
    range: EDLRange
    output_start: float

    @property
    def output_end(self) -> float:
        return self.output_start + self.range.output_duration

    def to_output(self, source_time: float) -> float | None:
        """Map a source timestamp into output time, or None if not in this slice."""
        if not (self.range.start <= source_time <= self.range.end):
            return None
        return self.output_start + (source_time - self.range.start) / self.range.speed

    def to_source(self, output_time: float) -> float | None:
        if not (self.output_start <= output_time <= self.output_end):
            return None
        return self.range.start + (output_time - self.output_start) * self.range.speed


class Timeline:
    """The output timeline built from an EDL."""

    def __init__(self, edl: EDL) -> None:
        self.edl = edl
        self.slices: list[TimelineSlice] = []
        cursor = 0.0
        for index, rng in enumerate(edl.ranges):
            self.slices.append(TimelineSlice(index=index, range=rng, output_start=cursor))
            cursor += rng.output_duration
        self.duration = cursor

    def slices_for_source(self, source_id: str) -> list[TimelineSlice]:
        return [s for s in self.slices if s.range.source == source_id]

    def map_to_output(self, source_id: str, source_time: float) -> list[float]:
        """Every output time a source instant appears at.

        A list, not a single value: the same moment can legitimately be used
        more than once in an edit.
        """
        out: list[float] = []
        for sl in self.slices:
            if sl.range.source != source_id:
                continue
            mapped = sl.to_output(source_time)
            if mapped is not None:
                out.append(mapped)
        return out

    def map_interval(self, source_id: str, start: float, end: float) -> list[tuple[float, float]]:
        """Map a source interval onto the output, clipped to what survives cuts.

        An interval that straddles a cut comes back as more than one piece, and
        one that was cut entirely comes back empty. This is what keeps captions
        aligned: a word only gets a cue for the part of it that is still there.
        """
        pieces: list[tuple[float, float]] = []
        for sl in self.slices:
            if sl.range.source != source_id:
                continue
            lo = max(start, sl.range.start)
            hi = min(end, sl.range.end)
            if hi <= lo:
                continue
            out_lo = sl.to_output(lo)
            out_hi = sl.to_output(hi)
            if out_lo is None or out_hi is None:
                continue
            pieces.append((out_lo, out_hi))
        return pieces

    def cut_boundaries(self) -> list[float]:
        """Output times where one range gives way to the next.

        These are the moments QA inspects: a bad splice shows up here or nowhere.
        """
        return [s.output_start for s in self.slices[1:]]
