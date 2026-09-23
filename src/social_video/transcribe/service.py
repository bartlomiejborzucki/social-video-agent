"""Transcription as a cached, resumable stage."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from social_video.errors import ValidationError
from social_video.ffmpeg.probe import probe
from social_video.fingerprint import file_fingerprint, options_fingerprint
from social_video.paths import normalize_user_path
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.transcript import Transcript
from social_video.transcribe.audio import extract_audio, guard_not_silent
from social_video.transcribe.base import (
    DEFAULT_BACKEND,
    BackendNotAvailableError,
    TranscriptionOptions,
    get_backend,
)
from social_video.transcribe.diarize import diarize, label_speakers, validate_diarization
from social_video.workspace.layout import Workspace

log = logging.getLogger(__name__)


def source_id_for(path: str | Path) -> str:
    """Stable, readable handle for a source file."""
    return Path(path).stem


def transcribe_source(
    source: str | Path,
    workspace: Workspace,
    *,
    options: TranscriptionOptions | None = None,
    backend_name: str | None = None,
    force: bool = False,
) -> Transcript:
    """Transcribe one source, reusing a cached result when it is still valid.

    The cache is keyed on the source's content fingerprint *and* every option
    that could change the result, so changing the model, the language, or the
    audio track re-transcribes, while merely re-running does not.
    """
    src = normalize_user_path(source, must_exist=True)
    opts = options or TranscriptionOptions()
    workspace.ensure()

    info = probe(src)
    sid = source_id_for(src)
    fingerprint = file_fingerprint(src)
    out_path = workspace.transcript_for(sid, opts.audio_track)
    # Constructing a backend is cheap; heavy imports wait for transcribe().
    backend = get_backend(backend_name)

    # The cache is content-addressed on (source content, options, backend), so
    # switching model, language or backend and switching back does not
    # re-transcribe. The default backend keeps the name it always had, so
    # existing caches stay valid. The path in `transcripts/` is the readable
    # "current" view, published from the cache.
    key = options_fingerprint(**opts.cache_fields())
    suffix = "" if backend.name == DEFAULT_BACKEND else f".{backend.name}"
    cache_path = workspace.cache / "transcripts" / f"{sid}.{fingerprint[:16]}.{key}{suffix}.json"

    if not force:
        cached = _load_if_valid(cache_path, fingerprint, opts, provider=backend.name)
        if cached is not None:
            log.info("transcript cache hit: %s", cache_path.name)
            _publish(cached, out_path)
            return cached
        log.info("transcript cache miss: %s", src.name)

    ok, reason = backend.validate_setup()
    if not ok:
        raise BackendNotAvailableError(f"transcription backend {backend.name!r}: {reason}")
    if opts.diarize:
        ok, reason = validate_diarization()
        if not ok:
            raise BackendNotAvailableError(reason)

    # Temp audio lives inside the workspace cache, not the system temp dir: a
    # two-hour take is a few hundred megabytes of PCM, and the workspace is the
    # place the user already expects to find (and be able to clear) our scratch.
    with tempfile.TemporaryDirectory(dir=workspace.cache) as tmp:
        audio = extract_audio(src, Path(tmp) / f"{sid}.wav", audio_track=opts.audio_track)
        guard_not_silent(audio, source_name=src.name, audio_track=opts.audio_track)
        log.info("transcribing %s with %s/%s", src.name, backend.name, opts.model)
        transcript = backend.transcribe(
            audio,
            options=opts,
            source_id=sid,
            source_fingerprint=fingerprint,
            duration=info.duration,
        )
        if opts.diarize:
            log.info("diarizing %s", src.name)
            transcript = label_speakers(transcript, diarize(audio, num_speakers=opts.num_speakers))

    if not transcript.words:
        log.warning("%s produced no words; the track may not contain speech", src.name)
    elif not transcript.has_word_timestamps:
        # Cutting on word boundaries is the premise. Say so loudly rather than
        # silently producing an edit whose cuts land mid-word.
        log.warning(
            "%s returned word timings that look evenly distributed rather than aligned; "
            "cuts placed from this transcript may not land on real word boundaries",
            backend.name,
        )

    save_artifact(transcript, cache_path)
    _publish(transcript, out_path)
    return transcript


def _publish(transcript: Transcript, out_path: Path) -> None:
    """Write the current transcript to its readable workspace path."""
    save_artifact(transcript, out_path)


def _load_if_valid(
    path: Path, fingerprint: str, options: TranscriptionOptions, *, provider: str
) -> Transcript | None:
    """Return the cached transcript only if it was produced from these inputs."""
    if not path.is_file():
        return None
    try:
        cached = load_artifact(Transcript, path)
    except ValidationError as exc:
        log.info("ignoring unreadable cached transcript %s: %s", path.name, exc)
        return None

    if cached.source_fingerprint != fingerprint:
        return None
    if cached.provider != provider:
        return None
    if cached.audio_track != options.audio_track:
        return None
    if options.language and cached.language != options.language:
        return None
    if cached.provider_model and cached.provider_model != options.model:
        return None
    return cached
