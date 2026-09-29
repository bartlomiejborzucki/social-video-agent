"""Measure a reference video's rhythm so an edit can be asked to feel like it.

"Make it feel like this one" is a common brief and a vague one. What can be
measured is the rhythm: how long shots last, how soon the first cut and the
first sentence land, how much of the running time is speech and how fast it
is spoken. Those numbers map onto settings this project already has --
`motion_energy`, a target shot length, a hook deadline -- which the agent can
propose and the user can accept.

The look (colour, type, graphics) is not measured. A contact sheet of one
frame per shot is written for the agent to judge it and choose a style pack.
Nothing of the reference is copied into the edit.
"""

from __future__ import annotations

import logging
from itertools import pairwise
from math import gcd
from pathlib import Path

import numpy as np

from social_video.analysis.scenes import detect_scenes, scene_cut_times
from social_video.analysis.silence import Pause, find_pauses, find_pauses_from_transcript
from social_video.errors import ValidationError
from social_video.ffmpeg.probe import probe
from social_video.fingerprint import file_fingerprint
from social_video.schemas.style_reference import (
    ShotRhythm,
    SpeechRhythm,
    StyleRecommendation,
    StyleReference,
)
from social_video.schemas.transcript import Transcript

log = logging.getLogger(__name__)

#: Median shot length below which a reference reads as bold, then as lively.
BOLD_BELOW = 2.0
LIVELY_BELOW = 5.0
#: Fast social edits cut shorter than the 0.6 s scene detection keeps by default.
MIN_SHOT = 0.2
#: Pauses shorter than this are breathing, not rhythm.
MIN_PAUSE = 0.35
#: Frames on the contact sheet; more is a wall, not a summary.
SHEET_FRAMES = 12

_COMMON_ASPECTS = {"9:16": 9 / 16, "4:5": 4 / 5, "1:1": 1.0, "16:9": 16 / 9}
_SENTENCE_END = (".", "!", "?", "…")


def shot_rhythm(cuts: list[float], duration: float) -> ShotRhythm:
    """Shot statistics from the cut instants of a ``duration``-second video."""
    inside = sorted(c for c in cuts if 0.0 < c < duration)
    edges = [0.0, *inside, duration]
    lengths = np.diff(np.array(edges, dtype=float))
    return ShotRhythm(
        count=len(lengths),
        cuts_per_minute=round(len(inside) * 60.0 / duration, 2),
        median_seconds=round(float(np.median(lengths)), 2),
        p25_seconds=round(float(np.percentile(lengths, 25)), 2),
        p75_seconds=round(float(np.percentile(lengths, 75)), 2),
        first_cut_seconds=round(inside[0], 2) if inside else None,
    )


def speech_rhythm(
    pauses: list[Pause], duration: float, *, transcript: Transcript | None = None
) -> SpeechRhythm:
    silent = sum(p.duration for p in pauses)
    words_per_minute = None
    first_sentence = None
    if transcript is not None and transcript.words:
        words = transcript.words
        spoken = max(words[-1].end - words[0].start - silent, 1.0)
        words_per_minute = round(len(words) * 60.0 / spoken, 1)
        first_sentence = next(
            (w.end for w in words if w.text.rstrip("\"')]}").endswith(_SENTENCE_END)), None
        )
    return SpeechRhythm(
        sound_ratio=round(min(1.0, max(0.0, 1.0 - silent / duration)), 3),
        pauses_per_minute=round(len(pauses) * 60.0 / duration, 2),
        longest_pause_seconds=round(max((p.duration for p in pauses), default=0.0), 2),
        words_per_minute=words_per_minute,
        first_sentence_seconds=None if first_sentence is None else round(first_sentence, 2),
    )


def recommend(shots: ShotRhythm, speech: SpeechRhythm | None) -> StyleRecommendation:
    reasons: list[str] = []
    if shots.count == 1:
        tight = speech is not None and speech.sound_ratio >= 0.9 and speech.pauses_per_minute < 4
        energy = "lively" if tight else "calm"
        target = 4.0 if tight else 8.0
        reasons.append(
            "no cut was detected: either one continuous shot or jump cuts in the same "
            "framing, which scene detection cannot see; check the contact sheet"
        )
        if tight:
            reasons.append("speech runs almost without pauses, so it was cut tight")
    else:
        median = shots.median_seconds
        energy = "bold" if median < BOLD_BELOW else "lively" if median < LIVELY_BELOW else "calm"
        target = min(10.0, max(1.0, median))
        reasons.append(
            f"median shot {median:.1f}s ({shots.cuts_per_minute:.0f} cuts a minute) "
            f"reads as {energy}"
        )

    if speech is not None and speech.first_sentence_seconds is not None:
        hook = speech.first_sentence_seconds
        reasons.append(f"the first sentence ends at {hook:.1f}s")
    elif shots.first_cut_seconds is not None:
        hook = shots.first_cut_seconds
        reasons.append(f"the first cut lands at {hook:.1f}s")
    else:
        hook = 3.0
    hook = min(5.0, max(1.5, hook))

    if speech is not None and speech.words_per_minute is not None:
        pace = speech.words_per_minute
        if pace >= 170:
            reasons.append(
                f"fast delivery ({pace:.0f} words a minute): tighten pauses, never speed up speech"
            )
        elif pace <= 120:
            reasons.append(f"unhurried delivery ({pace:.0f} words a minute): keep the pauses")

    return StyleRecommendation(
        motion_energy=energy,  # type: ignore[arg-type]
        target_shot_seconds=round(target, 1),
        hook_within_seconds=round(hook, 1),
        reasons=reasons,
    )


def aspect_label(width: int, height: int) -> str:
    ratio = width / height
    for label, value in _COMMON_ASPECTS.items():
        if abs(ratio - value) / value < 0.02:
            return label
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def sheet_moments(cuts: list[float], duration: float) -> list[tuple[float, str]]:
    """The middle of each shot, thinned evenly to at most ``SHEET_FRAMES``."""
    edges = [0.0, *sorted(c for c in cuts if 0.0 < c < duration), duration]
    shots = list(pairwise(edges))
    if len(shots) > SHEET_FRAMES:
        picks = np.linspace(0, len(shots) - 1, SHEET_FRAMES).round().astype(int)
        indexed = [(int(i), shots[int(i)]) for i in picks]
    else:
        indexed = list(enumerate(shots))
    return [
        ((start + end) / 2, f"shot {index + 1}  {end - start:.1f}s")
        for index, (start, end) in indexed
    ]


def analyze_reference(
    video: Path, *, transcript: Transcript | None = None, sheet: Path | None = None
) -> StyleReference:
    """Measure ``video``; write a contact sheet to ``sheet`` when given."""
    info = probe(video)
    if info.video is None:
        raise ValidationError(f"{video.name} has no video stream; a reference must be a video")
    if info.duration <= 0:
        raise ValidationError(f"{video.name} has no measurable duration")
    duration = info.duration
    width, height = info.video.display_size

    cuts = scene_cut_times(detect_scenes(video, min_scene_len=MIN_SHOT))
    shots = shot_rhythm(cuts, duration)

    speech = None
    if transcript is not None and transcript.words:
        pauses = find_pauses_from_transcript(transcript, minimum=MIN_PAUSE)
        speech = speech_rhythm(pauses, duration, transcript=transcript)
    elif info.audio:
        speech = speech_rhythm(find_pauses(video, minimum=MIN_PAUSE), duration)

    sheet_path = None
    if sheet is not None:
        from social_video.imaging import contact_sheet

        try:
            sheet_path = str(contact_sheet(video, sheet_moments(cuts, duration), sheet))
        except Exception as exc:  # the numbers stand without the sheet
            log.warning("could not draw the reference contact sheet: %s", exc)

    return StyleReference(
        reference=str(video),
        reference_fingerprint=file_fingerprint(video),
        duration=round(duration, 3),
        width=width,
        height=height,
        fps=round(info.video.fps_float, 3),
        aspect_ratio=aspect_label(width, height),
        shots=shots,
        speech=speech,
        recommendation=recommend(shots, speech),
        contact_sheet=sheet_path,
    )
