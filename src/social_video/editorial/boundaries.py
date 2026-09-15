"""Snapping cut points to places a cut can actually go.

A cut placed at an arbitrary timestamp clips the start of a word or leaves half
of one behind. The rule is: never cut inside a word when a phrase boundary is
nearby. Upstream states this as a hard rule and provides nothing that enforces
it -- and because its compact view exposes only phrase edges, an agent working
from that view cannot follow it even in principle.
"""

from __future__ import annotations

from dataclasses import dataclass

from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken

#: How far a boundary may move to reach a word edge. Beyond this, the requested
#: time was probably deliberate and is left alone.
DEFAULT_SEARCH = 0.35


@dataclass(frozen=True)
class SnapResult:
    start: float
    end: float
    #: What the boundary was moved to, for the record.
    start_reason: str = ""
    end_reason: str = ""


def snap_range(
    transcript: Transcript,
    start: float,
    end: float,
    *,
    padding: float = 0.08,
    search: float = DEFAULT_SEARCH,
    source_duration: float | None = None,
) -> SnapResult:
    """Move a range's edges onto word boundaries and add breathing room.

    The in-point moves to the start of the first word at or after it, and the
    out-point to the end of the last word at or before it, so a cut never
    clips a syllable. Padding is then added outside those edges, bounded by the
    surrounding silence so the padding cannot pull in a neighbouring word.
    """
    words = transcript.words
    if not words:
        return SnapResult(start=start, end=end, start_reason="no words to snap to")

    new_start, start_reason = _snap_in(words, start, search)
    new_end, end_reason = _snap_out(words, end, search)

    if new_end <= new_start:
        # The range collapsed; keep the caller's intent rather than invert it.
        return SnapResult(
            start=start,
            end=end,
            start_reason="snap would have inverted the range",
            end_reason="snap would have inverted the range",
        )

    padded_start = _pad_start(transcript, new_start, padding)
    padded_end = _pad_end(transcript, new_end, padding, source_duration)
    return SnapResult(
        start=padded_start,
        end=padded_end,
        start_reason=start_reason,
        end_reason=end_reason,
    )


def _snap_in(words: list[TranscriptToken], time: float, search: float) -> tuple[float, str]:
    """Round an in-point to the start of a word."""
    candidates = [w for w in words if abs(w.start - time) <= search]
    if not candidates:
        inside = [w for w in words if w.start < time < w.end]
        if inside:
            # Mid-word with nothing close: back up to the start of that word
            # rather than clipping its first syllable.
            return inside[0].start, f"backed up to the start of {inside[0].text!r}"
        return time, "left as requested"
    best = min(candidates, key=lambda w: abs(w.start - time))
    return best.start, f"snapped to the start of {best.text!r}"


def _snap_out(words: list[TranscriptToken], time: float, search: float) -> tuple[float, str]:
    """Round an out-point to the end of a word."""
    candidates = [w for w in words if abs(w.end - time) <= search]
    if not candidates:
        inside = [w for w in words if w.start < time < w.end]
        if inside:
            return inside[0].end, f"extended to the end of {inside[0].text!r}"
        return time, "left as requested"
    best = min(candidates, key=lambda w: abs(w.end - time))
    return best.end, f"snapped to the end of {best.text!r}"


def _pad_start(transcript: Transcript, time: float, padding: float) -> float:
    """Add lead-in, but never so much that the previous word is pulled in."""
    if padding <= 0:
        return max(0.0, time)
    previous_end = max((w.end for w in transcript.words if w.end <= time + 1e-6), default=0.0)
    available = max(0.0, time - previous_end)
    return max(0.0, time - min(padding, available))


def _pad_end(
    transcript: Transcript, time: float, padding: float, source_duration: float | None
) -> float:
    """Add tail, bounded by the next word and by the end of the source."""
    if padding <= 0:
        return time
    limit = source_duration if source_duration is not None else transcript.duration
    next_start = min(
        (w.start for w in transcript.words if w.start >= time - 1e-6),
        default=limit or (time + padding),
    )
    available = max(0.0, next_start - time)
    end = time + min(padding, available)
    return min(end, limit) if limit else end


def snap_ranges(
    transcript: Transcript,
    ranges: list[tuple[float, float]],
    *,
    padding: float = 0.08,
    search: float = DEFAULT_SEARCH,
    merge_gap: float = 0.05,
    source_duration: float | None = None,
) -> list[SnapResult]:
    """Snap several ranges, then merge any that padding pushed together.

    Without the merge step, two adjacent kept regions become two ranges with an
    audible seam between them where there should be continuous speech.
    """
    snapped = [
        snap_range(
            transcript,
            s,
            e,
            padding=padding,
            search=search,
            source_duration=source_duration,
        )
        for s, e in sorted(ranges)
    ]
    if not snapped:
        return []

    merged = [snapped[0]]
    for candidate in snapped[1:]:
        previous = merged[-1]
        if candidate.start - previous.end <= merge_gap:
            merged[-1] = SnapResult(
                start=previous.start,
                end=max(previous.end, candidate.end),
                start_reason=previous.start_reason,
                end_reason=candidate.end_reason,
            )
        else:
            merged.append(candidate)
    return merged


def words_in(transcript: Transcript, start: float, end: float) -> list[TranscriptToken]:
    return [w for w in transcript.words if w.start >= start - 1e-6 and w.end <= end + 1e-6]


def text_in(transcript: Transcript, start: float, end: float) -> str:
    return " ".join(w.text for w in words_in(transcript, start, end))


def pause_tokens(transcript: Transcript, minimum: float) -> list[TranscriptToken]:
    return [t for t in transcript.tokens if t.type is TokenType.SPACING and t.duration >= minimum]
