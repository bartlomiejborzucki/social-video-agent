"""Who spoke when: pyannote diarization, with the user's own token.

Opt-in, behind the ``diarize`` extra. The pyannote code is MIT, but the model
weights are gated: the user accepts the conditions of
``pyannote/speaker-diarization-community-1`` on Hugging Face and supplies their
own read token in ``HF_TOKEN``. The weights cannot be redistributed and a shared
token would break the terms, so there is no default.

The model is pinned and not configurable. ``speaker-diarization-precision-2``
loads through the same call but is a paid hosted API that uploads audio, so it
is never one configuration typo away.

Each word takes the speaker whose turn overlaps it most. Words no turn covers
keep no label, so a caption or framing decision never rests on a guess.
"""

from __future__ import annotations

import importlib.util
import os
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from social_video.errors import SocialVideoError
from social_video.schemas.transcript import TokenType, Transcript

MODEL = "pyannote/speaker-diarization-community-1"
TOKEN_VARIABLES = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")


@dataclass(frozen=True)
class Turn:
    start: float
    end: float
    speaker: str


def diarization_token() -> str | None:
    for name in TOKEN_VARIABLES:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


def validate_diarization() -> tuple[bool, str]:
    """Cheap: checked before any audio is decoded or any model downloaded."""
    if importlib.util.find_spec("pyannote.audio") is None:
        return False, (
            "speaker diarization needs pyannote: `pip install 'social-video-agent[diarize]'`"
        )
    if diarization_token() is None:
        return False, (
            f"speaker diarization needs your own Hugging Face read token in HF_TOKEN, after "
            f"accepting the conditions of {MODEL} on huggingface.co. The weights are gated "
            "and cannot be shared."
        )
    return True, ""


def diarize(audio: Path, *, num_speakers: int | None = None) -> list[Turn]:
    """Speaker turns for a prepared mono WAV, in time order."""
    ok, reason = validate_diarization()
    if not ok:
        raise SocialVideoError(reason)
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(MODEL, token=diarization_token())
    if pipeline is None:
        raise SocialVideoError(
            f"could not load {MODEL}: accept its conditions on huggingface.co with the "
            "account whose token is in HF_TOKEN"
        )
    kwargs = {"num_speakers": num_speakers} if num_speakers else {}
    result = pipeline(str(audio), **kwargs)
    # pyannote 4 wraps the annotation; 3.x returned it directly.
    annotation = getattr(result, "speaker_diarization", result)
    turns = [
        Turn(start=float(segment.start), end=float(segment.end), speaker=str(label))
        for segment, _track, label in annotation.itertracks(yield_label=True)
    ]
    return sorted(turns, key=lambda turn: turn.start)


def label_speakers(transcript: Transcript, turns: list[Turn]) -> Transcript:
    """A copy of the transcript with each word labelled by its main speaker.

    Labels are renamed ``S1``, ``S2``... in order of first appearance, so they
    read the same in captions, the packed transcript and the EDL whatever the
    diarizer called them.
    """
    ordered = sorted(turns, key=lambda turn: turn.start)
    starts = [turn.start for turn in ordered]
    names: dict[str, str] = {}
    labelled = transcript.model_copy(deep=True)
    for token in labelled.tokens:
        if token.type is not TokenType.WORD:
            continue
        speaker = _main_speaker(ordered, starts, token.start, token.end)
        if speaker is None:
            token.speaker = None
            continue
        token.speaker = names.setdefault(speaker, f"S{len(names) + 1}")
    for segment in labelled.segments:
        for token in segment.tokens:
            if token.type is TokenType.WORD:
                token.speaker = _main_speaker_name(ordered, starts, token.start, token.end, names)
    return labelled


def turns_from_transcript(transcript: Transcript) -> list[Turn]:
    """Speaker turns recovered from labelled words, joining a speaker's runs."""
    turns: list[Turn] = []
    for word in transcript.words:
        if word.speaker is None:
            continue
        if turns and turns[-1].speaker == word.speaker:
            turns[-1] = Turn(turns[-1].start, word.end, word.speaker)
        else:
            turns.append(Turn(word.start, word.end, word.speaker))
    return turns


def _main_speaker(ordered: list[Turn], starts: list[float], start: float, end: float) -> str | None:
    overlap: dict[str, float] = {}
    # Turns starting after the word ends cannot overlap it.
    for turn in ordered[: bisect_right(starts, end)]:
        shared = min(end, turn.end) - max(start, turn.start)
        if shared > 0:
            overlap[turn.speaker] = overlap.get(turn.speaker, 0.0) + shared
    if not overlap:
        return None
    return max(overlap, key=lambda speaker: overlap[speaker])


def _main_speaker_name(
    ordered: list[Turn], starts: list[float], start: float, end: float, names: dict[str, str]
) -> str | None:
    speaker = _main_speaker(ordered, starts, start, end)
    return names.get(speaker) if speaker is not None else None
