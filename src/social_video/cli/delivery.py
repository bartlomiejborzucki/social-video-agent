"""Covers, platform checks, QA, delivery and editorial review."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from social_video.cli._apps import (
    app,
)
from social_video.cli._common import _guard, _print_qa, console, err_console


@app.command()
def cover(
    workspace_dir: Path = typer.Argument(..., help="Edit workspace."),
    title: str = typer.Option(..., "--title", help="Headline drawn on the cover."),
    subtitle: str | None = typer.Option(None, "--subtitle"),
    plate: Path | None = typer.Option(
        None, "--plate", help="Generated background plate. Defaults to the recorded cover plate."
    ),
    frame_at: float | None = typer.Option(
        None, "--frame-at", help="Take the background from the finished video at this second."
    ),
    output: Path | None = typer.Option(None, "--output", "-o"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Compose the cover still: brand typography over a real frame or a plate."""
    from social_video.cover import CoverStyle, compose_cover, extract_frame
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.config import BrandContract
    from social_video.schemas.visuals import VisualAssets, VisualKind
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)
    contract = (
        _guard(lambda: load_artifact(BrandContract, ws.brand_contract))
        if ws.brand_contract.is_file()
        else None
    )
    style = CoverStyle.from_contract(contract) if contract else CoverStyle()
    if plate is None and frame_at is None and ws.visual_assets.is_file():
        assets = _guard(lambda: load_artifact(VisualAssets, ws.visual_assets))
        plate = next(
            (
                Path(item.path)
                for item in assets.visuals
                if item.kind is VisualKind.COVER_PLATE and Path(item.path).is_file()
            ),
            None,
        )
    frame: Path | None = None
    if plate is None:
        # A real frame of the speaker is the honest default, and on a host with
        # no image API it is the only one.
        source = ws.final / "final.mp4"
        if not source.is_file():
            source = ws.previews / "preview.mp4"
        if not source.is_file():
            err_console.print(
                "[red]error:[/red] no rendered video to take a cover frame from; "
                "render first, or pass --plate"
            )
            raise typer.Exit(1)
        frame_at = frame_at if frame_at is not None else 0.5
        frame = _guard(lambda: extract_frame(source, frame_at, ws.cache / "cover-frame.jpg"))
    target = output or ws.cover
    design = _guard(
        lambda: compose_cover(
            target,
            title=title,
            subtitle=subtitle,
            style=style,
            plate=plate,
            frame=frame,
            frame_at=frame_at,
        )
    )
    _guard(lambda: save_artifact(design, ws.cover_design))
    if as_json:
        console.print_json(design.to_json())
        return
    console.print(f"[green]cover[/green] {design.path} ({design.background})", soft_wrap=True)


@app.command()
def platforms(
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List publishing destinations and the feed UI they are expected to cover."""
    from social_video.profiles import available_platforms, load_platform

    specs = [load_platform(name) for name in available_platforms()]
    if as_json:
        console.print_json(
            json.dumps([spec.model_dump(mode="json", exclude={"schema_version"}) for spec in specs])
        )
        return
    table = Table(title="platforms", box=None, padding=(0, 2))
    for column in ("name", "reserved bottom", "reserved right", "max", "recommended"):
        table.add_column(column)
    for spec in specs:
        table.add_row(
            spec.name,
            f"{spec.reserved_bottom_pct:.0f}%",
            f"{spec.reserved_right_pct:.0f}%",
            f"{spec.max_duration:.0f}s",
            f"{spec.recommended_max_duration:.0f}s",
        )
    console.print(table)
    console.print(
        "[dim]Reserved zones are conservative estimates of the feed UI, not published "
        "specifications. Edit the JSON to correct them.[/dim]"
    )


@app.command()
def qa(
    workspace_dir: Path = typer.Argument(..., help="Workspace to check."),
    target: Path | None = typer.Option(None, "--output", help="File to inspect."),
    platform: list[str] | None = typer.Option(
        None, "--platform", help="Also check safe zones and limits for this platform; repeatable."
    ),
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

    report = _guard(lambda: stage_qa(target, edl, ws, platforms=platform or None))
    if as_json:
        console.print_json(report.to_json())
        raise typer.Exit(0 if report.passed else 1)
    _print_qa(report)
    raise typer.Exit(0 if report.passed else 1)


@app.command()
def deliver(
    workspace_dir: Path = typer.Argument(..., help="Completed edit workspace."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Durable destination."),
    with_captions: bool = typer.Option(False, "--with-captions"),
    no_captions: bool = typer.Option(False, "--no-captions"),
    srt: bool = typer.Option(False, "--srt"),
    vtt: bool = typer.Option(False, "--vtt"),
    poster: bool = typer.Option(False, "--poster", help="Raw frame grab."),
    cover: bool = typer.Option(False, "--cover", help="Composed cover still."),
    publish: bool = typer.Option(False, "--publish", help="Validated publish.json."),
    platform: list[str] | None = typer.Option(
        None, "--platform", help="Check delivered video against this platform; repeatable."
    ),
    resolution: list[str] | None = typer.Option(
        None, "--resolution", help="Additional WIDTHxHEIGHT variant; repeatable."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Create immutable Stage 5 variants and a verified delivery manifest."""
    from social_video.delivery import deliver_workspace
    from social_video.paths import normalize_user_path
    from social_video.workspace.layout import Workspace

    destination = _guard(lambda: normalize_user_path(output)) if output else None
    manifest = _guard(
        lambda: deliver_workspace(
            Workspace.at(workspace_dir),
            destination,
            with_captions=with_captions,
            no_captions=no_captions,
            srt=srt,
            vtt=vtt,
            poster=poster,
            cover=cover,
            publish=publish,
            platforms=platform or None,
            resolutions=resolution,
        )
    )
    if as_json:
        console.print_json(manifest.to_json())
    else:
        console.print(f"[green]delivered[/green] {manifest.destination}")
        manifest_path = Path(manifest.destination) / "delivery-manifest.json"
        console.print(f"[green]manifest[/green] {manifest_path}")


@app.command("apply-editorial-qa")
def apply_editorial_review(
    workspace_dir: Path = typer.Argument(..., help="Workspace containing qa-editorial.json."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Apply only the supervising editor's validated fixes to edl.json."""
    from social_video.editorial.review import apply_editorial_qa_artifacts
    from social_video.schemas.base import load_artifact, save_artifacts_atomically
    from social_video.schemas.captions import CaptionTrack
    from social_video.schemas.config import BrandContract
    from social_video.schemas.editorial_qa import EditorialQA
    from social_video.schemas.edl import EDL
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)
    edl = _guard(lambda: load_artifact(EDL, ws.edl))
    review = _guard(lambda: load_artifact(EditorialQA, ws.editorial_qa))
    caption_path = Path(edl.captions).with_suffix(".json") if edl.captions else None
    captions = (
        _guard(lambda: load_artifact(CaptionTrack, caption_path))
        if caption_path and caption_path.is_file()
        else None
    )
    style = (
        _guard(lambda: load_artifact(BrandContract, ws.brand_contract))
        if ws.brand_contract.is_file()
        else None
    )
    updated, updated_captions, updated_style, changed = _guard(
        lambda: apply_editorial_qa_artifacts(edl, review, captions=captions, style=style)
    )
    if changed:
        changes = {fix.artifact.value for fix in review.fixes}
        writes = {}
        if "edl" in changes:
            writes[ws.edl] = updated
        if "captions" in changes and updated_captions is not None and caption_path is not None:
            writes[caption_path] = updated_captions
        if "style" in changes and updated_style is not None:
            writes[ws.brand_contract] = updated_style
        _guard(lambda: save_artifacts_atomically(writes))
    result = {"status": review.status.value, "changed": changed, "edl": str(ws.edl)}
    if as_json:
        console.print_json(json.dumps(result))
    else:
        verb = "updated" if changed else "approved without changes"
        console.print(f"[green]{verb}[/green] {ws.edl}", soft_wrap=True)
