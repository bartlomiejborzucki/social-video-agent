"""Audio-correlated speaker selection: tracking, scoring, and declining to guess."""

from __future__ import annotations

import math

from social_video.reframe.detect import Face, FrameFaces
from social_video.reframe.speaker import choose_speaker, correlation, track_faces


def _face(x: float, y: float = 100.0, size: float = 80.0) -> Face:
    mouth_y = y + size * 0.7
    return Face(
        x=x,
        y=y,
        width=size,
        height=size,
        confidence=0.95,
        landmarks=(
            (x + size * 0.3, y + size * 0.3),
            (x + size * 0.7, y + size * 0.3),
            (x + size * 0.5, y + size * 0.5),
            (x + size * 0.35, mouth_y),
            (x + size * 0.65, mouth_y),
        ),
    )


def test_a_face_that_drifts_stays_one_track() -> None:
    samples = [FrameFaces(t=index * 0.16, faces=(_face(100 + index * 4),)) for index in range(10)]
    tracks = track_faces(samples)
    assert len(tracks) == 1
    assert tracks[0].coverage == 10


def test_two_people_become_two_tracks() -> None:
    samples = [FrameFaces(t=index * 0.16, faces=(_face(100), _face(600))) for index in range(8)]
    tracks = track_faces(samples)
    assert len(tracks) == 2
    assert all(track.coverage == 8 for track in tracks)


def test_a_face_that_leaves_and_returns_late_is_not_forced_into_the_old_track() -> None:
    present = [FrameFaces(t=index * 0.16, faces=(_face(100),)) for index in range(3)]
    gap = [FrameFaces(t=(3 + index) * 0.16, faces=()) for index in range(5)]
    back = [FrameFaces(t=(8 + index) * 0.16, faces=(_face(100),)) for index in range(3)]
    tracks = track_faces(present + gap + back)
    assert len(tracks) == 2


def test_correlation_needs_enough_samples_and_real_variance() -> None:
    assert correlation([1.0, 2.0], [1.0, 2.0]) == 0.0
    assert correlation([1.0] * 8, [0.2, 0.9] * 4) == 0.0
    aligned = [0.1, 0.9, 0.2, 0.8, 0.1, 0.95]
    assert correlation(list(aligned), aligned) > 0.99
    assert correlation([1 - v for v in aligned], aligned) < -0.99


def test_gaps_in_a_track_are_skipped_rather_than_treated_as_silence() -> None:
    motion: list[float | None] = [0.1, None, 0.9, None, 0.2, 0.8, 0.15, 0.85]
    speech = [0.1, 0.5, 0.9, 0.5, 0.2, 0.8, 0.15, 0.85]
    assert correlation(motion, speech) > 0.9


def _tracks_with(motions: list[list[float]]):
    samples = [
        FrameFaces(t=i * 0.16, faces=tuple(_face(100 + 500 * n) for n in range(len(motions))))
        for i in range(len(motions[0]))
    ]
    tracks = track_faces(samples)
    for track, series in zip(tracks, motions, strict=True):
        track.motion = dict(enumerate(series))
    return tracks, len(samples)


def test_the_face_whose_mouth_follows_the_audio_is_chosen() -> None:
    speech = [0.1, 0.9, 0.15, 0.85, 0.2, 0.95, 0.1, 0.9]
    talker = list(speech)
    listener = [0.5] * len(speech)
    listener[0] = 0.51
    tracks, count = _tracks_with([talker, listener])
    choice = choose_speaker(tracks, speech, count)
    assert choice.confident
    assert choice.track_id == tracks[0].id
    assert "correlated" in choice.reason


def test_nothing_is_claimed_when_no_mouth_follows_the_audio() -> None:
    speech = [0.1, 0.9, 0.15, 0.85, 0.2, 0.95, 0.1, 0.9]
    flat = [0.5, 0.5, 0.52, 0.5, 0.51, 0.5, 0.5, 0.52]
    tracks, count = _tracks_with([flat, [v * 0.9 for v in flat]])
    choice = choose_speaker(tracks, speech, count)
    assert not choice.confident
    assert "tracked the audio" in choice.reason


def test_two_equally_convincing_faces_produce_no_answer() -> None:
    speech = [0.1, 0.9, 0.15, 0.85, 0.2, 0.95, 0.1, 0.9]
    tracks, count = _tracks_with([list(speech), [v + 0.001 for v in speech]])
    choice = choose_speaker(tracks, speech, count)
    assert not choice.confident
    assert "equally" in choice.reason


def test_a_single_face_needs_no_speaker_resolution() -> None:
    tracks, count = _tracks_with([[0.5] * 6])
    choice = choose_speaker(tracks, [0.0] * 6, count)
    assert choice.confident
    assert "single tracked face" in choice.reason


def test_no_faces_at_all_is_reported_not_crashed() -> None:
    choice = choose_speaker([], [0.5, 0.5], 2)
    assert not choice.confident
    assert not math.isnan(choice.score)
