"""Render an EDL, alone or as the continuous legacy ``edit`` path."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.markup import escape

from social_video.cli._apps import (
    app,
)
from social_video.cli._common import _guard, _print_qa, console, err_console
from social_video.errors import SocialVideoError


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


@app.command()
def render(
    workspace_dir: Path = typer.Argument(..., help="Workspace containing edl.json."),
    quality: str = typer.Option("final", "--quality"),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Exact destination for preview.mp4 or final.mp4."
    ),
    renderer: str | None = typer.Option(
        None,
        "--renderer",
        help="remotion (default for new workflows) or ffmpeg.",
    ),
    remotion_license: str | None = typer.Option(
        None,
        "--remotion-license",
        help="License declaration when rendering without workflow-state.json.",
    ),
    audio_cleanup: bool = typer.Option(
        True,
        "--audio-cleanup/--no-audio-cleanup",
        help="Apply the project's measured voice cleanup. Off renders the audio as recorded.",
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Render the EDL already in a workspace. Deterministic and repeatable."""
    from social_video.paths import normalize_user_path
    from social_video.pipeline import load_workspace_artifacts, stage_render
    from social_video.schemas.base import load_artifact
    from social_video.schemas.motion import MotionPlan
    from social_video.schemas.workflow import (
        RemotionLicenseAttestation,
        Renderer,
    )
    from social_video.workflow import load_workflow
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
    license_root: Path | None = None
    if ws.workflow_state.is_file():
        workflow = _guard(lambda: load_workflow(ws))
        selected_renderer = _guard(lambda: Renderer(renderer)) if renderer else workflow.renderer
        attestation = workflow.remotion_license_attestation
        if remotion_license:
            attestation = _guard(lambda: RemotionLicenseAttestation(remotion_license))
        license_root = Path(workflow.target_project_root)
    else:
        selected_renderer = _guard(lambda: Renderer(renderer or "remotion"))
        attestation = (
            _guard(lambda: RemotionLicenseAttestation(remotion_license))
            if remotion_license
            else None
        )
    if selected_renderer is Renderer.REMOTION and attestation is None:
        # Same precedence as `workflow init`: an explicit flag, then this
        # edit's own state, then the declaration recorded for the project.
        from social_video.project_context import resolve_project_root
        from social_video.remotion_license import resolve_attestation

        root = license_root or _guard(resolve_project_root)
        attestation = _guard(lambda: resolve_attestation(root)[0])
    motion_plan = (
        _guard(lambda: load_artifact(MotionPlan, ws.motion_plan))
        if selected_renderer is Renderer.REMOTION and attestation is not None
        else None
    )
    rendered = _guard(
        lambda: stage_render(
            edl,
            manifest,
            ws,
            quality=quality,
            captions=captions,
            output=destination,
            renderer=selected_renderer,
            motion_plan=motion_plan,
            remotion_license_attestation=attestation,
            audio_cleanup=audio_cleanup,
        )
    )
    cleanup = _rendered_audio_cleanup(ws, rendered)
    if as_json:
        console.print_json(
            json.dumps(
                {
                    "output": str(rendered),
                    "quality": quality,
                    "renderer": selected_renderer.value,
                    "audio_cleanup": cleanup,
                },
                ensure_ascii=False,
            )
        )
        return
    console.print(f"[green]rendered[/green] {rendered}", soft_wrap=True)
    _print_audio_cleanup(cleanup)


def _rendered_audio_cleanup(workspace, rendered: Path) -> dict:
    """Read back what the render recorded about the audio, if anything."""
    from social_video.schemas.base import load_artifact
    from social_video.schemas.qa import RenderManifest

    path = workspace.renders / f"{rendered.stem}.manifest.json"
    if not path.is_file():
        return {}
    try:
        manifest = load_artifact(RenderManifest, path)
    except SocialVideoError:
        return {}
    return {"policy": manifest.audio_cleanup_policy, **manifest.audio_cleanup_applied}


def _print_audio_cleanup(cleanup: dict) -> None:
    """Say plainly whether the audio was changed, and how to get it back.

    Silence here would be the wrong default: a listener who is told nothing
    cannot tell a repaired recording from the one they made.
    """
    if not cleanup or cleanup.get("policy") in (None, "none"):
        return
    applied = cleanup.get("applied") or []
    if not applied:
        console.print("[dim]audio: left as recorded; nothing measured above its threshold[/dim]")
        return
    console.print("[yellow]audio was changed[/yellow] by measured voice cleanup:")
    for step in applied:
        console.print(
            f"  - {escape(str(step.get('reason', step.get('name', ''))))}", soft_wrap=True
        )
    if (cleanup.get("measured") or {}).get("clipped"):
        clipping = next(
            (step for step in cleanup.get("skipped") or [] if step.get("name") == "clipping"),
            None,
        )
        if clipping is not None:
            console.print(f"  [yellow]![/yellow] {escape(str(clipping['reason']))}", soft_wrap=True)
    console.print(
        "[dim]  to undo: re-render with --no-audio-cleanup, or set "
        "audio_cleanup_policy: none in .social-video/config.yaml[/dim]",
        soft_wrap=True,
    )


def _copy_output(source: Path, destination: Path) -> Path:
    from social_video.fsutil import atomic_copy

    return atomic_copy(source, destination)
