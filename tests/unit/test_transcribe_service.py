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


@requires_ffmpeg
def test_stage_one_records_transcript_quality(tmp_path: Path, fake: FakeBackend) -> None:
    import json

    from social_video.pipeline import stage_transcribe

    source = make_video(tmp_path / "clip.mp4", duration=1.5)
    ws = Workspace.at(tmp_path / "edit")

    stage_transcribe(source, ws, options=TranscriptionOptions(model="small"), backend="fake")

    quality = json.loads((ws.analysis / "clip.transcript-quality.json").read_text("utf-8"))
    assert quality["ok"] is True
    state = json.loads(ws.state.read_text("utf-8"))
    assert state["transcribe"]["quality_ok"] is True
    assert state["transcribe"]["suggested_model"] is None


@requires_ffmpeg
def test_a_corrected_workspace_transcript_wins_over_the_cache(
    tmp_path: Path, fake: FakeBackend
) -> None:
    from social_video.schemas.base import load_artifact, save_artifact

    source = make_video(tmp_path / "kamera.mp4", duration=1.5)
    ws = Workspace.at(tmp_path / "edit")
    options = TranscriptionOptions(model="medium", language="pl")
    service.transcribe_source(source, ws, options=options, backend_name="fake")
    path = ws.transcript_for("kamera")
    corrected = load_artifact(Transcript, path)
    corrected.tokens[1].text = "dobranoc"
    save_artifact(corrected, path)

    again = service.transcribe_source(source, ws, options=options, backend_name="fake")
    assert again.tokens[1].text == "dobranoc"
    assert load_artifact(Transcript, path).tokens[1].text == "dobranoc"
    assert len(fake.calls) == 1
    # Whatever model a later command defaults to, the correction is what compiles.
    found = service.workspace_transcript(source, ws)
    assert found is not None and found.tokens[1].text == "dobranoc"


@requires_ffmpeg
def test_a_workspace_transcript_of_another_file_is_not_used(
    tmp_path: Path, fake: FakeBackend
) -> None:
    source = make_video(tmp_path / "kamera.mp4", duration=1.5)
    ws = Workspace.at(tmp_path / "edit")
    service.transcribe_source(source, ws, backend_name="fake")
    make_video(tmp_path / "kamera.mp4", duration=2.0)
    assert service.workspace_transcript(source, ws) is None


@requires_ffmpeg
def test_refine_replaces_only_the_passage_and_keeps_the_stream_shape(
    tmp_path: Path, fake: FakeBackend
) -> None:
    from social_video.schemas.base import load_artifact
    from social_video.schemas.transcript import TokenType

    source = make_video(tmp_path / "kamera.mp4", duration=3.0)
    ws = Workspace.at(tmp_path / "edit")
    service.transcribe_source(source, ws, backend_name="fake")
    result = service.refine_transcript(
        source, ws, 0.45, 2.0, options=TranscriptionOptions(model="large-v3"), backend_name="fake"
    )
    assert [t.text for t in result.removed] == ["dobry"]
    assert [(t.text, t.start) for t in result.added] == [("Dzień", 0.55), ("dobry", 0.95)]
    saved = load_artifact(Transcript, ws.transcript_for("kamera"))
    assert [w.text for w in saved.words] == ["Dzień", "Dzień", "dobry"]
    gaps = [t for t in saved.tokens if t.type is TokenType.SPACING]
    assert gaps and all(g.end > g.start for g in gaps)
    assert saved.provider_options["refined 0.45-2.00"] == "fake/large-v3"
    assert fake.calls[-1].language == "pl"


def test_refine_spans_must_run_forward() -> None:
    from social_video.errors import ValidationError

    assert service.parse_span("51-56.5") == (51.0, 56.5)
    with pytest.raises(ValidationError):
        service.parse_span("56-51")
    with pytest.raises(ValidationError):
        service.parse_span("abc")


def test_a_passage_cut_mid_sentence_loses_its_closing_full_stop() -> None:
    added = [
        TranscriptToken(text="Rano", start=131.0, end=131.4),
        TranscriptToken(text="śniadaniem.", start=133.0, end=133.5),
    ]
    later = [TranscriptToken(text="potem", start=133.55, end=133.8)]
    joined = service._join_sentence(added, later, 133.53)
    assert [t.text for t in joined] == ["Rano", "śniadaniem"]
    capital = [TranscriptToken(text="Dzieci", start=133.55, end=133.8)]
    assert service._join_sentence(added, capital, 133.53)[-1].text == "śniadaniem."


@requires_ffmpeg
def test_a_word_cut_by_the_span_edge_is_kept(tmp_path: Path, fake: FakeBackend) -> None:
    from social_video.schemas.base import load_artifact

    source = make_video(tmp_path / "kamera.mp4", duration=3.0)
    ws = Workspace.at(tmp_path / "edit")
    service.transcribe_source(source, ws, backend_name="fake")
    # "dobry" (0.50-1.01) straddles the span's end; the passage cannot hear it whole.
    result = service.refine_transcript(
        source, ws, 0.05, 0.8, options=TranscriptionOptions(model="large-v3"), backend_name="fake"
    )
    assert [t.text for t in result.removed] == ["Dzień"]
    words = [w.text for w in load_artifact(Transcript, ws.transcript_for("kamera")).words]
    assert "dobry" in words


def test_a_stage_keeps_the_workspace_transcript_whatever_its_model(
    tmp_path: Path, fake: FakeBackend
) -> None:
    from social_video.pipeline import stage_transcribe

    source = make_video(tmp_path / "kamera.mp4", duration=1.5)
    ws = Workspace.at(tmp_path / "edit")
    medium = TranscriptionOptions(model="medium", language="pl")
    service.transcribe_source(source, ws, options=medium, backend_name="fake")
    again = stage_transcribe(source, ws, options=TranscriptionOptions(), backend="fake")
    assert again.provider_model == "medium"
    assert len(fake.calls) == 1
    forced = stage_transcribe(
        source, ws, options=TranscriptionOptions(), backend="fake", force=True
    )
    assert forced.provider_model == "small"


def test_a_word_repeated_across_the_span_edge_is_kept_once() -> None:
    added = [
        TranscriptToken(text="bardzo", start=157.59, end=157.81),
        TranscriptToken(text="długo", start=157.81, end=158.01),
    ]
    kept = [TranscriptToken(text="długo", start=158.03, end=158.19)]
    assert [t.text for t in service._drop_repeats_at_edges(added, kept, 155.17, 158.1)] == [
        "bardzo"
    ]
    other = [TranscriptToken(text="w", start=158.03, end=158.19)]
    assert len(service._drop_repeats_at_edges(added, other, 155.17, 158.1)) == 2
    # A word said again after the span (a false start) is not a duplicate.
    later = [TranscriptToken(text="długo", start=158.2, end=158.4)]
    assert len(service._drop_repeats_at_edges(added, later, 155.17, 158.1)) == 2
