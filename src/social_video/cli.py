"""Command line interface.

Every command that produces information supports ``--json``, because the
primary user of this CLI is a coding agent, not a person reading a table.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from social_video import __version__
from social_video.errors import SocialVideoError

app = typer.Typer(
    name="social-video-agent",
    help="Agent-native social video editor. Source media is never modified.",
    no_args_is_help=True,
    add_completion=False,
)
context_app = typer.Typer(help="Discover and cache target-project brand/editing context.")
workflow_app = typer.Typer(help="Persist and resume the guided multi-stage editing workflow.")
app.add_typer(context_app, name="context")
app.add_typer(workflow_app, name="workflow")
console = Console()
err_console = Console(stderr=True)


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show progress detail."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Errors only."),
) -> None:
    level = logging.DEBUG if verbose else logging.ERROR if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(message)s", stream=sys.stderr)


@app.command()
def version() -> None:
    """Print the version."""
    console.print(__version__)


# ---------------------------------------------------------------------------
# project context / staged workflow
# ---------------------------------------------------------------------------


@context_app.command("inspect")
def context_inspect(
    project_root: Path = typer.Argument(Path(), help="Target project, not skill root."),
    workspace_dir: Path | None = typer.Option(None, "--workspace", "-w"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Discover relevant local guidance without recursively ingesting the project."""
    from social_video.project_context import discover_project_context, resolve_project_root
    from social_video.workspace.layout import Workspace

    root = _guard(lambda: resolve_project_root(project_root))
    workspace = Workspace.at(workspace_dir or root / "edit")
    context, sources = _guard(lambda: discover_project_context(root, workspace))
    _print_context(context, sources, as_json=as_json)


@context_app.command("refresh")
def context_refresh(
    project_root: Path = typer.Argument(Path(), help="Target project, not skill root."),
    workspace_dir: Path | None = typer.Option(None, "--workspace", "-w"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Force a new bounded scan and replace cached project-context artifacts."""
    from social_video.project_context import discover_project_context, resolve_project_root
    from social_video.workspace.layout import Workspace

    root = _guard(lambda: resolve_project_root(project_root))
    workspace = Workspace.at(workspace_dir or root / "edit")
    context, sources = _guard(lambda: discover_project_context(root, workspace, refresh=True))
    _print_context(context, sources, as_json=as_json)


@workflow_app.command("init")
def workflow_init(
    source: Path = typer.Argument(..., help="Source media; it remains immutable."),
    workspace_dir: Path | None = typer.Option(None, "--workspace", "-w"),
    project_root: Path | None = typer.Option(None, "--project-root"),
    model_budget: str = typer.Option("balanced", "--model-budget"),
    workflow_mode: str = typer.Option("guided", "--workflow-mode"),
    quick: bool = typer.Option(False, "--quick", help="Continuous workflow on current model."),
    refresh_context: bool = typer.Option(False, "--refresh-context"),
    language: str = typer.Option("en", "--language"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Create Stage 0/1 state and context. Never renders video."""
    from social_video.paths import normalize_user_path
    from social_video.pipeline import stage_ingest
    from social_video.schemas.workflow import ModelBudget, WorkflowMode
    from social_video.workflow import create_workflow, workflow_status
    from social_video.workspace.layout import Workspace

    normalized_source = _guard(lambda: normalize_user_path(source, must_exist=True))
    workspace = (
        Workspace.at(workspace_dir) if workspace_dir else Workspace.for_source(normalized_source)
    )
    budget = _guard(lambda: ModelBudget(model_budget))
    mode = WorkflowMode.CONTINUOUS if quick else _guard(lambda: WorkflowMode(workflow_mode))
    _guard(lambda: stage_ingest(normalized_source, workspace))
    state = _guard(
        lambda: create_workflow(
            [normalized_source],
            workspace,
            project_root=project_root,
            model_budget=budget,
            workflow_mode=mode,
            refresh_context=refresh_context,
        )
    )
    payload = workflow_status(state, language=language)
    _print_workflow(payload, as_json=as_json)


@workflow_app.command("status")
def workflow_show_status(
    workspace_dir: Path = typer.Argument(Path(), help="Edit workspace."),
    language: str = typer.Option("en", "--language"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Report persisted state, missing artifacts, and the recommended handoff."""
    from social_video.workflow import load_workflow, workflow_status
    from social_video.workspace.layout import Workspace

    state = _guard(lambda: load_workflow(Workspace.at(workspace_dir)))
    _print_workflow(workflow_status(state, language=language), as_json=as_json)


@workflow_app.command("resume")
def workflow_resume(
    workspace_dir: Path = typer.Argument(Path(), help="Edit workspace."),
    language: str = typer.Option("en", "--language"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Resume from files only; equivalent to workflow status."""
    workflow_show_status(workspace_dir, language, as_json)


@workflow_app.command("complete")
def workflow_complete(
    stage: int = typer.Argument(..., min=1, max=5),
    workspace_dir: Path = typer.Option(Path(), "--workspace", "-w"),
    language: str = typer.Option("en", "--language"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Validate the current stage artifacts, persist completion, and stop/handoff."""
    from social_video.schemas.workflow import WorkflowStage
    from social_video.workflow import advance_workflow, workflow_status
    from social_video.workspace.layout import Workspace

    stages = {
        1: WorkflowStage.EDITORIAL_PLAN,
        2: WorkflowStage.EXECUTION,
        3: WorkflowStage.EDITORIAL_REVIEW,
        4: WorkflowStage.FINALIZATION,
        5: WorkflowStage.DELIVERY,
    }
    state = _guard(lambda: advance_workflow(Workspace.at(workspace_dir), stages[stage]))
    _print_workflow(workflow_status(state, language=language), as_json=as_json)


def _print_context(context, sources, *, as_json: bool) -> None:
    payload = {
        "target_project_root": context.target_project_root,
        "cache_status": context.cache_status,
        "explicit_config": context.explicit_config,
        "project_context": context.model_dump(mode="json", exclude={"schema_version"}),
        "sources": [
            {
                "path": item.path,
                "type": item.source_type,
                "confidence": item.confidence.value,
                "relevance": item.relevance,
            }
            for item in sources.sources
        ],
        "conflicts": context.conflicts,
        "unknowns": context.unknowns,
    }
    if as_json:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    console.print(f"[bold]Project context[/bold]  {escape(context.target_project_root)}")
    if sources.sources:
        for item in sources.sources[:10]:
            console.print(
                f"  - {escape(item.path)} ({item.confidence.value}, {item.relevance}/100)"
            )
    else:
        console.print("  No brandbook or project-specific video guidance found; use defaults.")
    if context.claims:
        console.print("[bold]Explicit facts[/bold]")
        for claim in context.claims[:5]:
            console.print(
                f"  - {escape(claim.category)}.{escape(claim.key)} = "
                f"{escape(str(claim.value))} ({escape(claim.source)})"
            )
    console.print(f"[green]{context.cache_status}[/green]")


def _print_workflow(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    polish = payload.get("language") == "pl"
    console.print(f"[bold]{escape(payload['current_stage'])}[/bold]")
    if payload["missing_artifacts"]:
        missing_label = "Brakujące artefakty etapu:" if polish else "Missing for this stage:"
        console.print(f"[yellow]{missing_label}[/yellow]")
        for path in payload["missing_artifacts"]:
            console.print(f"  - {escape(path)}")
    if payload["handoff_required"]:
        model_label = "Zalecane modele" if polish else "Recommended models"
        effort_label = "Poziom rozumowania" if polish else "Reasoning"
        console.print(f"[bold]{model_label}[/bold]")
        models = payload.get("next_models") or {"openai": payload["next_model"]}
        provider_labels = {"openai": "OpenAI", "claude": "Claude"}
        for provider, model in models.items():
            label = provider_labels.get(provider, provider.title())
            console.print(f"  {label}: [cyan]{escape(model)}[/cyan]")
        console.print(f"{effort_label}: {escape(payload['reasoning_effort'])}")
    else:
        console.print(
            "Kontynuuj bieżącym modelem (tryb continuous)."
            if polish
            else "Continue with the current model (continuous mode)."
        )
    console.print(escape(payload["reason"]))
    if payload["next_prompt"]:
        if payload["handoff_required"]:
            label = "Po zmianie modelu wyślij" if polish else "After switching, send"
        else:
            label = "Kontynuuj poleceniem" if polish else "Continue with"
        console.print(f'{label}: "{escape(payload["next_prompt"])}"')


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


@app.command()
def doctor(
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    install_ffmpeg: bool = typer.Option(
        False, "--install-ffmpeg", help="Download a static ffmpeg into the app cache."
    ),
) -> None:
    """Check that this machine can actually produce a correct video."""
    from social_video.doctor import run_doctor

    if install_ffmpeg:
        from social_video.ffmpeg.bootstrap import install_static_ffmpeg

        path = install_static_ffmpeg(progress=not as_json)
        console.print(f"[green]ffmpeg installed:[/green] {path}")

    report = run_doctor()

    if as_json:
        console.print_json(json.dumps(report.to_dict()))
        raise typer.Exit(0 if report.ok else 1)

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("")
    table.add_column("check")
    table.add_column("detail", overflow="fold")
    marks = {
        "OK": "[green]OK[/green]",
        "OPTIONAL": "[blue]OPTIONAL[/blue]",
        "WARNING": "[yellow]WARNING[/yellow]",
        "MISSING": "[red]MISSING[/red]",
        "ERROR": "[red]ERROR[/red]",
    }
    for check in report.checks:
        # Detail text contains things like "[align]" which rich would eat as markup.
        table.add_row(marks[check.status], escape(check.name), escape(check.detail))
    console.print(table)

    actionable = [c for c in report.checks if c.remedy]
    if actionable:
        console.print("\n[bold]What to do[/bold]")
        for check in actionable:
            colour = "red" if check.required else "yellow"
            console.print(f"  [{colour}]{escape(check.name)}[/{colour}]: {escape(check.remedy)}")

    if report.ok:
        console.print("\n[green]READY[/green]")
    else:
        console.print(f"\n[red]NOT READY: {len(report.failures)} blocking problem(s).[/red]")
    raise typer.Exit(0 if report.ok else 1)


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# transcribe
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# pack
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# profiles
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


@app.command()
def edit(
    source: Path = typer.Argument(..., help="Source video."),
    workspace_dir: Path | None = typer.Option(None, "--workspace", "-w"),
    profile: str = typer.Option("talking-head", "--profile", "-p"),
    brand: str = typer.Option("default", "--brand", "-b"),
    quality: str = typer.Option("final", "--quality", help="draft, preview or final."),
    model: str = typer.Option("small", "--model", help="Transcription model size."),
    language: str | None = typer.Option(None, "--language"),
    audio_track: int = typer.Option(
        0,
        "--audio-track",
        help="Zero-based audio track. Multi-track recordings are common: OBS puts "
        "desktop audio on track 0 and the microphone on track 1. Run `inspect` "
        "to see what a file actually has.",
    ),
    backend: str | None = typer.Option(None, "--backend", help="Transcription backend."),
    force: bool = typer.Option(False, "--force", help="Re-transcribe even if cached."),
    reframe: str | None = typer.Option(
        None, "--reframe", help="fit, center, face or speaker. Default: the profile's."
    ),
    goal: str = typer.Option("", "--goal"),
    no_captions: bool = typer.Option(False, "--no-captions"),
    output_dir: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Copy the finished video to a file or directory (Windows paths work in WSL).",
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Run the whole pipeline: transcribe, plan, cut, reframe, caption, QA."""
    from social_video.pipeline import run_edit
    from social_video.schemas.edl import ReframeMode
    from social_video.transcribe.base import TranscriptionOptions
    from social_video.workspace.layout import Workspace

    if quality not in ("draft", "preview", "final"):
        err_console.print(f"[red]error:[/red] unknown quality {quality!r}")
        raise typer.Exit(1)
    mode = None
    if reframe:
        try:
            mode = ReframeMode(reframe)
        except ValueError:
            err_console.print(
                f"[red]error:[/red] unknown reframe mode {reframe!r}; expected one of "
                + ", ".join(m.value for m in ReframeMode)
            )
            raise typer.Exit(1) from None

    copy_destination: Path | None = None
    if output_dir is not None:
        from social_video.paths import normalize_user_path

        requested = _guard(lambda: normalize_user_path(output_dir))
        source_path = _guard(lambda: normalize_user_path(source, must_exist=True))
        copy_destination = (
            requested / f"{source_path.stem or 'final'}.mp4"
            if requested.suffix.lower() != ".mp4"
            else requested
        )
        same_path = copy_destination.resolve(strict=False) == source_path
        same_file = copy_destination.exists() and copy_destination.samefile(source_path)
        if same_path or same_file:
            err_console.print("[red]error:[/red] output must not overwrite the source video")
            raise typer.Exit(1)

    ws = Workspace.at(workspace_dir) if workspace_dir else Workspace.for_source(source)
    output, report = _guard(
        lambda: run_edit(
            source,
            ws,
            profile_name=profile,
            brand_name=brand,
            quality=quality,
            options=TranscriptionOptions(model=model, language=language, audio_track=audio_track),
            backend=backend,
            force=force,
            goal=goal,
            reframe=mode,
            skip_captions=no_captions,
        )
    )

    if copy_destination is not None:
        output = _guard(lambda: _copy_output(output, copy_destination))

    if as_json:
        console.print_json(
            json.dumps(
                {
                    "output": str(output),
                    "workspace": str(ws.root),
                    "qa_passed": report.passed,
                    "errors": [c.message for c in report.errors],
                    "warnings": [c.message for c in report.warnings],
                }
            )
        )
        raise typer.Exit(0 if report.passed else 1)

    _print_qa(report)
    console.print(f"\n[green]output[/green] {output}", soft_wrap=True)
    console.print(f"[green]workspace[/green] {ws.root}", soft_wrap=True)
    raise typer.Exit(0 if report.passed else 1)


# ---------------------------------------------------------------------------
# render / qa
# ---------------------------------------------------------------------------


@app.command()
def render(
    workspace_dir: Path = typer.Argument(..., help="Workspace containing edl.json."),
    quality: str = typer.Option("final", "--quality"),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Exact destination for preview.mp4 or final.mp4."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Render the EDL already in a workspace. Deterministic and repeatable."""
    from social_video.paths import normalize_user_path
    from social_video.pipeline import load_workspace_artifacts, stage_render
    from social_video.workspace.layout import Workspace

    if quality not in ("draft", "preview", "final"):
        err_console.print(f"[red]error:[/red] unknown quality {quality!r}")
        raise typer.Exit(1)
    ws = Workspace.at(workspace_dir)
    manifest, edl = _guard(lambda: load_workspace_artifacts(ws))
    destination = _guard(lambda: normalize_user_path(output)) if output else None
    if destination is not None:
        source_paths = {entry.resolved_path().resolve() for entry in manifest.sources}
        if destination.resolve(strict=False) in source_paths:
            err_console.print("[red]error:[/red] output must not overwrite source media")
            raise typer.Exit(1)
    captions = Path(edl.captions) if edl.captions else None
    rendered = _guard(
        lambda: stage_render(
            edl, manifest, ws, quality=quality, captions=captions, output=destination
        )
    )
    if as_json:
        console.print_json(json.dumps({"output": str(rendered), "quality": quality}))
        return
    console.print(f"[green]rendered[/green] {rendered}", soft_wrap=True)


@app.command()
def qa(
    workspace_dir: Path = typer.Argument(..., help="Workspace to check."),
    target: Path | None = typer.Option(None, "--output", help="File to inspect."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect a rendered file against its EDL."""
    from social_video.pipeline import load_workspace_artifacts, stage_qa
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)
    _, edl = _guard(lambda: load_workspace_artifacts(ws))
    if target is None:
        candidates = sorted(ws.final.glob("*.mp4")) + sorted(ws.previews.glob("*.mp4"))
        if not candidates:
            err_console.print(f"[red]error:[/red] no rendered video found in {ws.root}")
            raise typer.Exit(1)
        target = candidates[0]

    report = _guard(lambda: stage_qa(target, edl, ws))
    if as_json:
        console.print_json(report.to_json())
        raise typer.Exit(0 if report.passed else 1)
    _print_qa(report)
    raise typer.Exit(0 if report.passed else 1)


@app.command("apply-editorial-qa")
def apply_editorial_review(
    workspace_dir: Path = typer.Argument(..., help="Workspace containing qa-editorial.json."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Apply only the supervising editor's validated fixes to edl.json."""
    from social_video.editorial.review import apply_editorial_qa
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.editorial_qa import EditorialQA
    from social_video.schemas.edl import EDL
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)
    edl = _guard(lambda: load_artifact(EDL, ws.edl))
    review = _guard(lambda: load_artifact(EditorialQA, ws.editorial_qa))
    updated, changed = _guard(lambda: apply_editorial_qa(edl, review))
    if changed:
        _guard(lambda: save_artifact(updated, ws.edl))
    result = {"status": review.status.value, "changed": changed, "edl": str(ws.edl)}
    if as_json:
        console.print_json(json.dumps(result))
    else:
        verb = "updated" if changed else "approved without changes"
        console.print(f"[green]{verb}[/green] {ws.edl}", soft_wrap=True)


def _print_qa(report) -> None:
    console.print("[bold]QA[/bold]")
    for check in report.checks:
        if check.passed:
            mark = "[green]ok[/green]  "
        elif check.accepted:
            mark = "[cyan]accepted[/cyan]"
        elif check.severity.value == "error":
            mark = "[red]FAIL[/red]"
        else:
            mark = "[yellow]warn[/yellow]"
        console.print(f"  {mark} {escape(check.name)}: {escape(check.message)}")
    if report.status == "passed":
        console.print("[green]passed[/green]")
    elif report.status == "passed_with_warnings":
        console.print("[yellow]passed_with_warnings[/yellow]")
    else:
        console.print(f"[red]{len(report.errors)} problem(s)[/red]")
        if report.exhausted:
            console.print(
                "[yellow]repair budget exhausted; reporting rather than retrying[/yellow]"
            )


def _guard(fn):
    """Run an operation, turning our own exceptions into clean CLI errors.

    An agent reading stderr should get the actionable message, not a traceback.
    """
    try:
        return fn()
    except (SocialVideoError, ValueError, RuntimeError) as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except FileNotFoundError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except OSError as exc:
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            raise
        err_console.print(f"[red]error:[/red] file operation failed: {exc}")
        raise typer.Exit(1) from exc


def _copy_output(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.{uuid4().hex}.partial")
    try:
        shutil.copy2(source, partial)
        with partial.open("rb") as handle:
            os.fsync(handle.fileno())
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


if __name__ == "__main__":
    app()
