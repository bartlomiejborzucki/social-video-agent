"""Claude Motion segments: the CLI writes the spec and imports the export.

The film itself is written by a Claude session with its artifact tools and
exported by the user; nothing here talks to Motion.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape

from social_video.cli._apps import film_app
from social_video.cli._common import _guard, console


@film_app.command("spec")
def film_spec(
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    scene: list[str] = typer.Option(
        [],
        "--scene",
        help="Graphic type to author in Motion (repeat): hook_card, chapter, cta, "
        "end_card or quote. Default: every one of those in the motion plan.",
    ),
    film_id: str | None = typer.Option(None, "--film-id", help="Default: <edl name>-film."),
    title: str | None = typer.Option(None, "--title"),
    claude_motion: str = typer.Option(
        "unknown_to_cli",
        "--claude-motion",
        help="available or unavailable, as the agent sees the Motion type in its own tools.",
    ),
    allow_brand_upload: bool = typer.Option(
        False,
        "--allow-brand-upload",
        help="The user agrees, for this film, to upload the logo and brand font file.",
    ),
    force: bool = typer.Option(False, "--force", help="Replace a spec with imported segments."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Write a film spec, Motion's scenes.json and base.css for a Claude session."""
    from social_video.errors import ValidationError
    from social_video.motion.film import build_film_spec, write_film_spec
    from social_video.schemas.base import load_artifact
    from social_video.schemas.config import BrandContract
    from social_video.schemas.edl import EDL
    from social_video.schemas.motion import MotionPlan
    from social_video.schemas.visuals import CapabilityState
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        try:
            state = CapabilityState(claude_motion)
        except ValueError as exc:
            raise ValidationError(
                "--claude-motion is available, unavailable or unknown_to_cli"
            ) from exc
        if state is CapabilityState.UNAVAILABLE:
            raise ValidationError(
                "this session has no Claude Motion; keep the Remotion graphics instead"
            )
        for path, label in ((ws.edl, "EDL"), (ws.motion_plan, "motion plan")):
            if not path.is_file():
                raise ValidationError(f"no {label} at {path}")
        contract = (
            load_artifact(BrandContract, ws.brand_contract) if ws.brand_contract.is_file() else None
        )
        spec = build_film_spec(
            load_artifact(EDL, ws.edl),
            load_artifact(MotionPlan, ws.motion_plan),
            contract,
            types=scene or None,
            film_id=film_id,
            title=title,
            allow_brand_upload=allow_brand_upload,
            claude_motion=state,
        )
        return spec, write_film_spec(ws, spec, force=force)

    spec, path = _guard(run)
    if as_json:
        console.print_json(spec.to_json())
        return
    console.print(
        f"film [bold]{escape(spec.film_id)}[/bold]: {spec.width}x{spec.height} at "
        f"{spec.fps} fps, {spec.duration:.1f} s"
    )
    for s in spec.scenes:
        console.print(
            f"  {s.id:14} {s.duration:4.1f}s  @{s.start_in_output:6.2f}s  {escape(s.text)}"
        )
    if spec.extended_letters:
        console.print(
            f"  [yellow]letters beyond the built-in faces:[/yellow] {escape(spec.extended_letters)}"
            " -- name a Google family that has them"
        )
    if spec.brand_upload == "none":
        console.print("  brand files stay local: no logo in the film, font by family name only")
    console.print(f"[green]written[/green] {path}", soft_wrap=True)


@film_app.command("import")
def film_import(
    export: Path = typer.Argument(..., help="The MP4 the user exported from the film's page."),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    film_id: str = typer.Option(..., "--film-id"),
    font_used: str = typer.Option(
        ..., "--font-used", help="The font family the film's text is set in."
    ),
    scene: list[str] = typer.Option([], "--scene", help="Scene id to import (repeat)."),
    tolerance_frames: float = typer.Option(
        1.0, "--tolerance-frames", help="How far the export's length may differ, in frames."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Cut the export into one segment per scene and place each in edl.json."""
    from social_video.motion.film import import_film
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)
    segments = _guard(
        lambda: import_film(
            ws,
            export,
            film_id=film_id,
            font_used=font_used,
            scene_ids=scene or None,
            tolerance_frames=tolerance_frames,
        )
    )
    if as_json:
        console.print_json(data=[s.model_dump(mode="json") for s in segments])
        return
    for s in segments:
        replaced = s.replaced_element.type.value if s.replaced_element else "nothing"
        console.print(
            f"  {s.scene_id:14} @{s.start_in_output:6.2f}s {s.duration:4.1f}s  "
            f"replaces {replaced}  sha256={s.sha256[:12]}"
        )
    console.print(f"{len(segments)} segment(s) placed in [green]{ws.edl}[/green]", soft_wrap=True)


@film_app.command("remove")
def film_remove(
    scene_id: str = typer.Argument(..., help="Scene id, e.g. hook-card-1."),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    film_id: str = typer.Option(..., "--film-id"),
) -> None:
    """Take a segment out of the edit and put back the graphic it replaced."""
    from social_video.motion.film import remove_film_segment
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)
    segment = _guard(lambda: remove_film_segment(ws, film_id, scene_id))
    restored = segment.replaced_element.type.value if segment.replaced_element else "nothing"
    console.print(f"removed {segment.film_id}/{segment.scene_id}; restored {restored}")


@film_app.command("status")
def film_status(
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Films specified, scenes imported, and what is still waiting for an export."""
    from social_video.motion.film import load_registry
    from social_video.workspace.layout import Workspace

    registry = _guard(lambda: load_registry(Workspace.at(workspace_dir)))
    pending = [f"{film}/{scene}" for film, scene in registry.pending()]
    if as_json:
        console.print_json(
            data={
                "films": [r.film_id for r in registry.films],
                "imported": [f"{s.film_id}/{s.scene_id}" for s in registry.segments],
                "pending": pending,
            }
        )
        return
    if not registry.films:
        console.print("No Motion film specified for this edit.")
        return
    for record in registry.films:
        console.print(f"film {escape(record.film_id)}: {escape(record.spec_path)}", soft_wrap=True)
    for s in registry.segments:
        console.print(f"  imported {s.film_id}/{s.scene_id}  font={escape(s.font_used)}")
    for name in pending:
        console.print(f"  [yellow]waiting[/yellow] {name}")
