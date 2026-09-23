"""Who spoke when, from gated pyannote weights to a frame that follows the floor.

pyannote is never installed in CI (its weights need the user's own token), so
the pipeline object is a stand-in with pyannote's real call shape.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from social_video.errors import SocialVideoError
from social_video.reframe.detect import Face, FrameFaces
from social_video.reframe.plan import _follow_turns
from social_video.reframe.speaker import FaceTrack, assign_speakers, speaker_at
from social_video.schemas.transcript import Transcript, TranscriptToken
from social_video.transcribe import diarize as diarize_module
from social_video.transcribe.diarize import (
    MODEL,
    Turn,
    diarize,
    label_speakers,
    turns_from_transcript,
    validate_diarization,
)
from social_video.transcribe.normalize import synthesize_spacing


def _transcript() -> Transcript:
    words = [
        TranscriptToken(text="Cześć", start=0.0, end=0.4),
        TranscriptToken(text="Marku.", start=0.5, end=0.9),
        TranscriptToken(text="Hej!", start=1.5, end=1.8),
        TranscriptToken(text="Co", start=2.0, end=2.2),
        TranscriptToken(text="słychać?", start=2.2, end=2.7),
        TranscriptToken(text="(szum)", start=5.0, end=5.3),
    ]
    return Transcript(
        source_id="rozmowa",
        source_fingerprint="f" * 16,
        duration=6.0,
        provider="test",
        tokens=synthesize_spacing(words),
    )


def test_diarization_says_what_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diarize_module.importlib.util, "find_spec", lambda name: None)
    assert "social-video-agent[diarize]" in validate_diarization()[1]

    monkeypatch.setattr(diarize_module.importlib.util, "find_spec", lambda name: object())
    for name in diarize_module.TOKEN_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    ok, reason = validate_diarization()
    assert not ok
    assert "HF_TOKEN" in reason and MODEL in reason


def test_the_pinned_free_model_is_loaded_with_the_users_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded: dict[str, object] = {}

    class Segment:
        def __init__(self, start: float, end: float) -> None:
            self.start, self.end = start, end

    class Annotation:
        def itertracks(self, yield_label: bool = False):
            yield Segment(1.4, 2.8), "B", "SPEAKER_01"
            yield Segment(0.0, 1.0), "A", "SPEAKER_00"

    class Pipeline:
        @classmethod
        def from_pretrained(cls, model, token=None):
            loaded.update(model=model, token=token)
            return cls()

        def __call__(self, audio, **kwargs):
            loaded["kwargs"] = kwargs
            return types.SimpleNamespace(speaker_diarization=Annotation())

    audio = types.ModuleType("pyannote.audio")
    audio.Pipeline = Pipeline  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyannote", types.ModuleType("pyannote"))
    monkeypatch.setitem(sys.modules, "pyannote.audio", audio)
    monkeypatch.setattr(diarize_module.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("HF_TOKEN", "hf_user_token")

    turns = diarize(Path("audio.wav"), num_speakers=2)

    assert loaded == {"model": MODEL, "token": "hf_user_token", "kwargs": {"num_speakers": 2}}
    assert "precision" not in MODEL
    assert [t.speaker for t in turns] == ["SPEAKER_00", "SPEAKER_01"]


def test_a_missing_token_stops_before_loading_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diarize_module.importlib.util, "find_spec", lambda name: object())
    for name in diarize_module.TOKEN_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SocialVideoError, match="HF_TOKEN"):
        diarize(Path("audio.wav"))


def test_words_take_the_speaker_they_overlap_most_and_labels_read_s1_s2() -> None:
    turns = [
        Turn(0.0, 1.0, "SPEAKER_07"),
        Turn(1.4, 2.4, "SPEAKER_03"),
        Turn(2.4, 3.0, "SPEAKER_07"),
    ]

    labelled = label_speakers(_transcript(), turns)

    assert [(w.text, w.speaker) for w in labelled.words] == [
        ("Cześć", "S1"),
        ("Marku.", "S1"),
        ("Hej!", "S2"),
        ("Co", "S2"),
        # Mostly inside the later turn.
        ("słychać?", "S1"),
        # No turn covers it, so it gets no guess.
        ("(szum)", None),
    ]
    assert labelled.speakers == ["S1", "S2"]
    assert [(t.speaker, t.start, t.end) for t in turns_from_transcript(labelled)] == [
        ("S1", 0.0, 0.9),
        ("S2", 1.5, 2.2),
        ("S1", 2.2, 2.7),
    ]


def _two_faces(samples: int) -> tuple[list[FrameFaces], list[FaceTrack]]:
    left = Face(x=100, y=100, width=100, height=120, confidence=0.9)
    right = Face(x=900, y=100, width=100, height=120, confidence=0.9)
    frames = [FrameFaces(t=i * 0.5, faces=(left, right)) for i in range(samples)]
    tracks = [FaceTrack(id=0), FaceTrack(id=1)]
    for index in range(samples):
        tracks[0].faces[index] = left
        tracks[1].faces[index] = right
        # The left person's mouth moves in the first half, the right one's after.
        speaking_left = frames[index].t < samples * 0.25
        tracks[0].motion[index] = 0.9 if speaking_left else 0.1
        tracks[1].motion[index] = 0.1 if speaking_left else 0.9
    return frames, tracks


def test_each_speaker_is_matched_to_the_face_that_moves_in_their_turns() -> None:
    frames, tracks = _two_faces(20)
    turns = [(0.0, 5.0, "S1"), (5.0, 10.0, "S2")]

    assert assign_speakers(tracks, [f.t for f in frames], turns) == {"S1": 0, "S2": 1}


def test_a_short_interjection_does_not_take_the_frame() -> None:
    times = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
    turns = [(0.0, 1.2, "S1"), (1.3, 1.8, "S2"), (1.8, 3.5, "S1")]

    assert speaker_at(times, turns) == ["S1", "S1", "S1", "S1", "S1", "S1", "S1"]


def test_the_frame_follows_the_floor_and_cuts_at_turn_changes() -> None:
    frames, tracks = _two_faces(20)
    turns = [(0.0, 5.0, "S1"), (5.0, 10.0, "S2")]

    followed = _follow_turns(frames, tracks, turns)

    assert followed is not None
    kept, cuts, note = followed
    assert cuts == [5.0]
    assert all(sample.faces[0].x == 100 for sample in kept if sample.t < 5.0)
    assert all(sample.faces[0].x == 900 for sample in kept if sample.t >= 5.0)
    assert "S1->face 0" in note and "S2->face 1" in note


def test_speakers_that_cannot_be_matched_leave_single_speaker_framing() -> None:
    frames, tracks = _two_faces(20)
    for track in tracks:
        track.motion = dict.fromkeys(track.motion, 0.5)

    assert _follow_turns(frames, tracks, [(0.0, 5.0, "S1"), (5.0, 10.0, "S2")]) is None
