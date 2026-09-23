"""Transcription is chosen by name, validated cheaply, and cached on its inputs."""

from __future__ import annotations

from pathlib import Path

import pytest

from social_video.schemas.transcript import Transcript, TranscriptToken
from social_video.transcribe import base, service
from social_video.transcribe.base import (
    BackendNotAvailableError,
    TranscriptionOptions,
    get_backend,
    register_backend,
)
from social_video.workspace.layout import Workspace
from tests.conftest import make_video, requires_ffmpeg


class FakeBackend:
    name = "fake"

    def __init__(self, *, usable: bool = True) -> None:
        self.usable = usable
        self.calls: list[TranscriptionOptions] = []

    def validate_setup(self) -> tuple[bool, str]:
        return (True, "") if self.usable else (False, "install the fake extra")

    def transcribe(self, audio, *, options, source_id, source_fingerprint, duration):
        assert audio.is_file(), "audio is extracted before the backend runs"
        self.calls.append(options)
        return Transcript(
            source_id=source_id,
            source_fingerprint=source_fingerprint,
            duration=duration,
            language=options.language or "pl",
            provider=self.name,
            provider_model=options.model,
            tokens=[
                TranscriptToken(text="Dzień", start=0.10, end=0.42),
                TranscriptToken(text="dobry", start=0.50, end=1.01),
            ],
        )


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    backend = FakeBackend()
    # Register the built-ins first, so the copy the test mutates holds them and
    # the restored original is not left without them.
    base._load_builtin_backends()
    monkeypatch.setattr(base, "_REGISTRY", dict(base._REGISTRY))
    register_backend("fake", lambda: backend)
    return backend


def test_an_unknown_backend_names_the_available_ones(fake: FakeBackend) -> None:
    with pytest.raises(BackendNotAvailableError, match=r"'nope'.*Available: .*fake"):
        get_backend("nope")


def test_the_environment_selects_the_backend(
    fake: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOCIAL_VIDEO_TRANSCRIBER", " Fake ")

    assert get_backend() is fake


def test_the_default_backend_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOCIAL_VIDEO_TRANSCRIBER", raising=False)

    assert get_backend().name == "faster-whisper"


@requires_ffmpeg
def test_a_second_run_is_served_from_the_cache(tmp_path: Path, fake: FakeBackend) -> None:
    source = make_video(tmp_path / "Mój film.mp4", duration=1.5)
    workspace = Workspace.at(tmp_path / "edit")

    first = service.transcribe_source(source, workspace, backend_name="fake")
    second = service.transcribe_source(source, workspace, backend_name="fake")

    assert len(fake.calls) == 1
    assert second == first
    assert workspace.transcript_for("Mój film", 0).is_file()


@requires_ffmpeg
def test_changing_an_option_or_forcing_transcribes_again(tmp_path: Path, fake: FakeBackend) -> None:
    source = make_video(tmp_path / "clip.mp4", duration=1.5)
    workspace = Workspace.at(tmp_path / "edit")

    service.transcribe_source(source, workspace, backend_name="fake")
    service.transcribe_source(
        source, workspace, backend_name="fake", options=TranscriptionOptions(model="medium")
    )
    service.transcribe_source(source, workspace, backend_name="fake", force=True)
    # Switching back to a model already seen is a cache hit, not a third decode.
    service.transcribe_source(
        source, workspace, backend_name="fake", options=TranscriptionOptions(model="medium")
    )

    assert [call.model for call in fake.calls] == ["small", "medium", "small"]


@requires_ffmpeg
def test_an_unusable_backend_fails_before_any_audio_is_decoded(
    tmp_path: Path, fake: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_video(tmp_path / "clip.mp4", duration=1.0)
    fake.usable = False

    def no_decoding(*args, **kwargs):
        raise AssertionError("audio must not be extracted for an unusable backend")

    monkeypatch.setattr(service, "extract_audio", no_decoding)

    with pytest.raises(BackendNotAvailableError, match="install the fake extra"):
        service.transcribe_source(source, Workspace.at(tmp_path / "edit"), backend_name="fake")


@requires_ffmpeg
def test_switching_backend_is_a_cache_miss_and_switching_back_a_hit(
    tmp_path: Path, fake: FakeBackend
) -> None:
    other = FakeBackend()
    other.name = "other"
    register_backend("other", lambda: other)
    source = make_video(tmp_path / "clip.mp4", duration=1.0)
    workspace = Workspace.at(tmp_path / "edit")

    service.transcribe_source(source, workspace, backend_name="fake")
    switched = service.transcribe_source(source, workspace, backend_name="other")
    service.transcribe_source(source, workspace, backend_name="fake")

    assert len(fake.calls) == 1
    assert len(other.calls) == 1
    assert switched.provider == "other"


@requires_ffmpeg
def test_diarization_labels_words_and_is_checked_before_decoding(
    tmp_path: Path, fake: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from social_video.transcribe.diarize import Turn

    source = make_video(tmp_path / "rozmowa.mp4", duration=1.5)
    options = TranscriptionOptions(diarize=True)
    monkeypatch.setattr(service, "validate_diarization", lambda: (False, "needs HF_TOKEN"))

    with pytest.raises(BackendNotAvailableError, match="needs HF_TOKEN"):
        service.transcribe_source(
            source, Workspace.at(tmp_path / "edit"), backend_name="fake", options=options
        )
    assert fake.calls == []

    monkeypatch.setattr(service, "validate_diarization", lambda: (True, ""))
    monkeypatch.setattr(
        service,
        "diarize",
        lambda audio, num_speakers=None: [Turn(0.0, 0.45, "A"), Turn(0.45, 1.2, "B")],
    )
    transcript = service.transcribe_source(
        source, Workspace.at(tmp_path / "edit"), backend_name="fake", options=options
    )

    assert [w.speaker for w in transcript.words] == ["S1", "S2"]
