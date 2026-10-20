"""Range edges where the speech actually starts and stops.

Whisper's word times are good enough to find a word, not to cut on. Two
failures recur: the last word of a range "ends" before its final syllable
does (``wieczorem`` reported to 10.66 s, audible to ~10.9 s), so the edit
closes on an open mouth; and the first word of a range swallows the silence
before it (``6.28 s`` reported, voice from ``6.74 s``), so the edit opens on
dead air.

So after a range is snapped to words, each outer edge is moved to the
acoustic boundary of the speech within ``SEARCH`` seconds of the word edge,
measured as an RMS envelope against the local noise floor, and the profile's
padding is added there for the breath. The move never crosses a neighbouring
word, and every move is reported, so a compile says what it changed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from social_video.analysis.speech import FRAME, MIN_RUN, decode_mono, envelope_db, speech_mask
from social_video.schemas.transcript import Transcript, TranscriptToken

#: How far from the word edge the speech boundary is looked for.
SEARCH = 0.4
#: The breath kept outside the speech, clamped to this range.
MIN_MARGIN = 0.08
MAX_MARGIN = 0.12
#: Context decoded either side of an edge to measure the noise floor.
CONTEXT = 1.5
#: Moves smaller than this are not worth reporting.
REPORT_THRESHOLD = 0.03
#: Speech this long past the final out-point means the edit cuts a word.
TAIL_WINDOW = 0.3

#: Mono float samples at ``RATE`` for ``(source_id, start, end)``.
Loader = Callable[[str, float, float], np.ndarray]


@dataclass(frozen=True)
class EdgeShift:
    source: str
    edge: str
    word: str
    word_time: float
    new_time: float
    reason: str

    @property
    def delta(self) -> float:
        return self.new_time - self.word_time

    def describe(self) -> str:
        return (
            f"{self.source} {self.edge} {self.word_time:.2f}s -> {self.new_time:.2f}s "
            f"({self.delta:+.2f}s, {self.word!r}): {self.reason}"
        )


@dataclass
class AcousticEdges:
    """Moves range edges to speech boundaries; remembers what it moved."""

    load: Loader
    search: float = SEARCH
    shifts: list[EdgeShift] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def refine(
        self,
        transcript: Transcript,
        start: float,
        end: float,
        *,
        padding: float,
        limit_end: float | None = None,
    ) -> tuple[float, float]:
        """New (start, end) for a range already snapped to words and padded.

        ``limit_end`` caps the out-point, e.g. at the end of the picture a
        voice is laid under.
        """
        words = transcript.words
        inside = [w for w in words if w.end > start + 1e-6 and w.start < end - 1e-6]
        if not inside:
            return start, end
        margin = min(MAX_MARGIN, max(MIN_MARGIN, padding))
        duration = transcript.duration
        first, last = inside[0], inside[-1]
        new_start = self._in_point(transcript, first, margin, fallback=start)
        new_end = self._out_point(transcript, last, margin, fallback=end, duration=duration)
        if limit_end is not None:
            new_end = min(new_end, max(limit_end, end))
        if new_end - new_start < 0.08:
            return start, end
        return round(new_start, 3), round(new_end, 3)

    def check_tail(self, transcript: Transcript, end: float) -> float:
        """Seconds of speech right after ``end``; non-zero means a word is cut."""
        if end >= transcript.duration - FRAME:
            return 0.0
        low = max(0.0, end - CONTEXT)
        high = min(transcript.duration, end + max(CONTEXT, TAIL_WINDOW))
        db = envelope_db(self.load(transcript.source_id, low, high))
        mask = speech_mask(db)
        first = round((end - low) / FRAME)
        after = mask[first : first + int(TAIL_WINDOW / FRAME)]
        if after.size == 0 or not after[: MIN_RUN + 1].any():
            return 0.0
        run = 0
        for value in after:
            if not value:
                break
            run += 1
        return run * FRAME

    def _window(self, source: str, low: float, high: float) -> tuple[np.ndarray, float]:
        low = max(0.0, low)
        db = envelope_db(self.load(source, low, high))
        return speech_mask(db), low

    def _in_point(
        self, transcript: Transcript, word: TranscriptToken, margin: float, *, fallback: float
    ) -> float:
        previous = _neighbour_before(transcript.words, word)
        floor = previous.end if previous is not None else 0.0
        low = max(floor, word.start - self.search)
        # The onset lies inside the word, which may be much longer than the
        # search window when whisper glued silence onto it.
        high = max(word.start + self.search, min(word.end, word.start + 1.0))
        mask, origin = self._window(transcript.source_id, low - CONTEXT, high + CONTEXT)
        first = round((low - origin) / FRAME)
        last = round((high - origin) / FRAME)
        span = mask[first:last]
        if span.size == 0 or not span.any():
            return fallback
        if span[0]:
            # Speech already running at the window edge: the sound before the
            # word is still the word, or another one. Leave it to the words.
            return fallback
        onset = origin + (first + int(np.argmax(span))) * FRAME
        new = onset - min(margin, onset - low)
        new = max(0.0, new)
        self._record(transcript.source_id, "in", word, fallback, new, onset, word.start)
        return new

    def _out_point(
        self,
        transcript: Transcript,
        word: TranscriptToken,
        margin: float,
        *,
        fallback: float,
        duration: float,
    ) -> float:
        following = _neighbour_after(transcript.words, word)
        ceiling = following.start if following is not None else duration
        low = max(word.start, word.end - self.search)
        high = min(ceiling, word.end + self.search, duration)
        if high - low < FRAME * MIN_RUN:
            return fallback
        mask, origin = self._window(transcript.source_id, low - CONTEXT, high + CONTEXT)
        first = round((low - origin) / FRAME)
        last = round((high - origin) / FRAME)
        span = mask[first:last]
        if span.size == 0 or not span.any():
            return fallback
        offset = origin + (first + len(span) - int(np.argmax(span[::-1]))) * FRAME
        silent_after = high - offset
        new = offset + min(margin, max(0.0, silent_after) if following else margin)
        new = min(new, duration, ceiling)
        self._record(transcript.source_id, "out", word, fallback, new, offset, word.end)
        return new

    def _record(
        self,
        source: str,
        edge: str,
        word: TranscriptToken,
        before: float,
        after: float,
        boundary: float,
        word_time: float,
    ) -> None:
        if abs(after - before) < REPORT_THRESHOLD:
            return
        where = "starts" if edge == "in" else "stops"
        self.shifts.append(
            EdgeShift(
                source=source,
                edge=edge,
                word=word.text,
                word_time=round(before, 3),
                new_time=round(after, 3),
                reason=(f"speech {where} at {boundary:.2f}s, the transcript says {word_time:.2f}s"),
            )
        )


def _neighbour_before(words: list[TranscriptToken], word: TranscriptToken):
    before = [w for w in words if w.end <= word.start + 1e-6 and w is not word]
    return before[-1] if before else None


def _neighbour_after(words: list[TranscriptToken], word: TranscriptToken):
    after = [w for w in words if w.start >= word.end - 1e-6 and w is not word]
    return after[0] if after else None


def file_loader(paths: dict[str, tuple[Path, int]]) -> Loader:
    """Decode short spans of each source's transcribed track with ffmpeg."""

    def load(source_id: str, start: float, end: float) -> np.ndarray:
        path, track = paths[source_id]
        return decode_mono(path, track=track, start=max(0.0, start), end=end)

    return load
