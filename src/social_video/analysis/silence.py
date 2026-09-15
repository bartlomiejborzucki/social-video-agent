"""Finding pauses, and deciding which of them are worth tightening.

The default posture is restraint. Pauses are part of speech: removing all of
them produces the breathless, wrong-sounding edit that gives automated cutting
a bad name. Only pauses longer than a profile's threshold are candidates, and
even those are tightened to a floor rather than closed completely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from social_video.ffmpeg.run import run_ffmpeg
from social_video.schemas.transcript import TokenType, Transcript

_SILENCE_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class Pause:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def tightened_to(self, keep: float) -> tuple[float, float]:
        """The span to remove if this pause is shortened to ``keep`` seconds.

        The kept portion is split across both sides so the speech either side
        keeps its breathing room, rather than butting straight up against the
        cut.
        """
        if self.duration <= keep:
            return (self.start, self.start)
        margin = keep / 2.0
        return (self.start + margin, self.end - margin)


def find_pauses_from_transcript(transcript: Transcript, *, minimum: float = 0.5) -> list[Pause]:
    """Pauses derived from word timings.

    Preferred over waveform silence detection because it knows the difference
    between a pause in speech and a quiet passage that still has speech in it.
    """
    pauses = [
        Pause(start=token.start, end=token.end)
        for token in transcript.tokens
        if token.type is TokenType.SPACING and token.duration >= minimum
    ]
    words = transcript.words
    if words:
        # Leading and trailing dead air, which is nearly always unwanted.
        if words[0].start >= minimum:
            pauses.insert(0, Pause(start=0.0, end=words[0].start))
        if transcript.duration - words[-1].end >= minimum:
            pauses.append(Pause(start=words[-1].end, end=transcript.duration))
    return pauses


def find_pauses(video: Path, *, threshold_db: float = -40.0, minimum: float = 0.5) -> list[Pause]:
    """Pauses detected from the waveform, for sources without a transcript."""
    stderr = run_ffmpeg(
        [
            "-i",
            str(video),
            "-af",
            f"silencedetect=noise={threshold_db}dB:d={minimum}",
            "-f",
            "null",
            "-",
        ],
        desc=f"detect silence in {video.name}",
        timeout=3600,
    )
    starts = [float(x) for x in _SILENCE_START.findall(stderr)]
    ends = [float(x) for x in _SILENCE_END.findall(stderr)]
    return [Pause(start=s, end=e) for s, e in zip(starts, ends, strict=False) if e > s]
