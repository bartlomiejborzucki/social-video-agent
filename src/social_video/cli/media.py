"""Inspect, transcribe and plan: everything before the first render."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.markup import escape
from rich.table import Table

from social_video.cli._apps import (
    app,
)
from social_video.cli._common import _guard, console, err_console


@app.command()
def inspect(
    source: Path = typer.Argument(..., help="Video or audio file to inspect."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Probe a source file and report what it actually is."""
    from social_video.ffmpeg.probe import probe

    info = _guard(lambda: probe(source))
    video = info.video
    payload = {
        "path": str(info.path),
        "duration": round(info.duration, 3),
        "size_bytes": info.size_bytes,
        "format": info.format_name,
        "video": None
        if video is None
        else {
            "codec": video.codec,
            "stored_size": [video.width, video.height],
            "display_size": list(video.display_size),
            "rotation": video.rotation,
            "frame_rate": video.frame_rate,
            "fps": round(video.fps_float, 4),
            "pix_fmt": video.pix_fmt,
            "is_portrait": video.is_portrait,
            "is_hdr": video.is_hdr,
        },
        "audio_tracks": [
            {
                "index": a.index,
                "codec": a.codec,
                "channels": a.channels,
                "sample_rate": a.sample_rate,
                "language": a.language,
            }
            for a in info.audio
        ],
    }
    if as_json:
        console.print_json(json.dumps(payload))
        return

    console.print(f"[bold]{info.path.name}[/bold]")
    console.print(f"  duration     {info.duration:.2f}s")
    if video:
        w, h = video.display_size
        console.print(f"  video        {video.codec} {w}x{h} @ {video.fps_float:.3f} fps")
        if video.rotation:
            console.print(
                f"  rotation     {video.rotation}deg "
                f"(stored {video.width}x{video.height}, displays {w}x{h})"
            )
        console.print(f"  orientation  {'portrait' if video.is_portrait else 'landscape'}")
        if video.is_hdr:
            console.print(f"  [yellow]HDR[/yellow]        {video.color_transfer}")
    if not info.audio:
        console.print("  [red]audio        none - this cannot be transcribed[/red]")
    for a in info.audio:
        lang = f" [{a.language}]" if a.language else ""
        console.print(f"  audio {a.index}      {a.codec} {a.channels}ch {a.sample_rate}Hz{lang}")
    if len(info.audio) > 1:
        console.print(
            "  [yellow]note[/yellow]         multiple audio tracks; pick one with --audio-track"
        )


@app.command()
def transcribe(
    source: Path = typer.Argument(..., help="Video or audio file."),
    workspace_dir: Path | None = typer.Option(
        None, "--workspace", "-w", help="Workspace directory (default: <source dir>/edit)."
    ),
    backend: str | None = typer.Option(None, "--backend", help="Transcription backend."),
    model: str = typer.Option("small", "--model", help="Model size for local backends."),
    language: str | None = typer.Option(
        None, "--language", help="ISO code, e.g. en or pl. Omit to auto-detect."
    ),
    audio_track: int = typer.Option(0, "--audio-track", help="Zero-based audio track."),
    no_vad: bool = typer.Option(False, "--no-vad", help="Disable voice-activity filtering."),
    force: bool = typer.Option(False, "--force", help="Re-transcribe even if cached."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Transcribe a source locally. Cached on source content plus options."""
    from social_video.transcribe.base import TranscriptionOptions
    from social_video.transcribe.service import transcribe_source
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir) if workspace_dir else Workspace.for_source(source)
    options = TranscriptionOptions(
        language=language, model=model, vad=not no_vad, audio_track=audio_track
    )
    transcript = _guard(
        lambda: transcribe_source(source, ws, options=options, backend_name=backend, force=force)
    )
    path = ws.transcript_for(transcript.source_id, audio_track)

    if as_json:
        console.print_json(
            json.dumps(
                {
                    "transcript": str(path),
                    "provider": transcript.provider,
                    "model": transcript.provider_model,
                    "language": transcript.language,
                    "words": len(transcript.words),
                    "duration": transcript.duration,
                    "word_timestamps_reliable": transcript.has_word_timestamps,
                    "speakers": transcript.speakers,
                }
            )
        )
        return

    console.print(f"[green]transcribed[/green] {transcript.source_id}")
    console.print(f"  backend    {transcript.provider} / {transcript.provider_model}")
    console.print(f"  language   {transcript.language}")
    console.print(f"  words      {len(transcript.words)}")
    console.print(f"  written    {path}", soft_wrap=True)
    if not transcript.has_word_timestamps and transcript.words:
        console.print(
            "  [yellow]warning[/yellow]    word timings look evenly distributed rather than "
            "aligned; cuts may not land on word boundaries"
        )


@app.command()
def pack(
    workspace_dir: Path = typer.Argument(..., help="Workspace or project directory."),
    silence: float = typer.Option(0.5, "--silence", help="Gap that starts a new phrase."),
    max_words: int = typer.Option(28, "--max-words", help="Cap on words per phrase."),
) -> None:
    """Build the compact transcript the agent reads."""
    from social_video.schemas.base import load_artifact
    from social_video.schemas.transcript import Transcript
    from social_video.transcript.pack import pack_transcripts
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)
    files = sorted(ws.transcripts.glob("*.json"))
    if not files:
        err_console.print(
            f"[red]no transcripts in {ws.transcripts}[/red]\n"
            f"Run `social-video-agent transcribe <source>` first."
        )
        raise typer.Exit(1)

    transcripts = [load_artifact(Transcript, f) for f in files]
    document = _guard(
        lambda: pack_transcripts(
            transcripts, silence=silence, max_words=max_words, output=ws.packed_transcript
        )
    )
    # The document contains literal `[start-end]` ranges, so markup must be off,
    # and paths must not be hard-wrapped: an agent copies them verbatim.
    console.print(document, markup=False, highlight=False, soft_wrap=True)
    err_console.print(f"[green]written[/green] {ws.packed_transcript}", soft_wrap=True)


@app.command()
def profiles(
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List the available output profiles and brand profiles."""
    from social_video.profiles import (
        available_brands,
        available_profiles,
        load_brand,
        load_profile,
    )

    out: dict[str, Any] = {
        "profiles": [
            {
                "name": n,
                "description": load_profile(n).description,
                "size": [load_profile(n).width, load_profile(n).height],
                "reframe": load_profile(n).default_reframe,
            }
            for n in available_profiles()
        ],
        "brands": [
            {"name": n, "description": load_brand(n).description} for n in available_brands()
        ],
    }
    if as_json:
        console.print_json(json.dumps(out))
        return
    table = Table(title="output profiles", box=None, padding=(0, 2))
    table.add_column("name")
    table.add_column("size")
    table.add_column("reframe")
    table.add_column("description", overflow="fold")
    for p in out["profiles"]:
        table.add_row(
            p["name"], f"{p['size'][0]}x{p['size'][1]}", p["reframe"], escape(p["description"])
        )
    console.print(table)
    brands = Table(title="brand profiles", box=None, padding=(0, 2))
    brands.add_column("name")
    brands.add_column("description", overflow="fold")
    for b in out["brands"]:
        brands.add_row(b["name"], escape(b["description"]))
    console.print(brands)


@app.command()
def plan(
    source: Path = typer.Argument(..., help="Source video."),
    workspace_dir: Path | None = typer.Option(None, "--workspace", "-w"),
    profile: str = typer.Option("talking-head", "--profile", "-p"),
    goal: str = typer.Option("", "--goal", help="What this edit is for."),
    model: str = typer.Option("small", "--model", help="Transcription model size."),
    language: str | None = typer.Option(None, "--language"),
    audio_track: int = typer.Option(
        0, "--audio-track", help="Zero-based audio track. See `inspect`."
    ),
    backend: str | None = typer.Option(None, "--backend"),
    force: bool = typer.Option(False, "--force", help="Re-transcribe even if cached."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Write a mechanical first-pass edit plan for the agent to revise.

    This removes only what can be found from timing: dead air, isolated filler,
    and immediately repeated phrases. Decisions about meaning are yours.
    """
    from social_video.pipeline import stage_plan, stage_transcribe
    from social_video.profiles import load_profile
    from social_video.transcribe.base import TranscriptionOptions
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir) if workspace_dir else Workspace.for_source(source)
    prof = _guard(lambda: load_profile(profile))
    options = TranscriptionOptions(model=model, language=language, audio_track=audio_track)
    transcript = _guard(
        lambda: stage_transcribe(source, ws, options=options, backend=backend, force=force)
    )
    result = _guard(lambda: stage_plan(transcript, ws, prof, goal=goal))

    if as_json:
        console.print_json(result.to_json())
        return
    console.print(f"[bold]{result.goal}[/bold]  (profile: {result.profile})")
    console.print(escape(result.strategy))
    console.print()
    for item in result.items:
        console.print(
            f"  [yellow]{item.action.value:6}[/yellow] "
            f"[{item.start:7.2f}-{item.end:7.2f}] {escape(item.reason)}"
        )
    if result.open_questions:
        console.print("\n[bold]Worth deciding[/bold]")
        for question in result.open_questions:
            console.print(f"  - {escape(question)}")
    console.print(f"\n[green]written[/green] {ws.edit_plan}", soft_wrap=True)
