"""The recordings a workspace knows about."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape

from social_video.cli._apps import sources_app
from social_video.cli._common import _guard, console


@sources_app.command("add")
def sources_add(
    files: list[Path] = typer.Argument(..., help="Recordings to add; they remain immutable."),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    source_id: str | None = typer.Option(
        None, "--id", help="Id plans and EDLs use for it (one file only). Default: file stem."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Add recordings to an existing workspace's source manifest.

    Probes and fingerprints each file. Transcripts, plans and workflow state
    are left as they are; transcribe a new recording with `transcribe -w`.
    """
    from social_video.paths import normalize_user_path
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.source import SourceManifest
    from social_video.sources import add_source
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        if source_id is not None and len(files) != 1:
            raise ValueError("--id names one file; add several files without it")
        if not ws.exists:
            raise ValueError(f"no workspace at {ws.root}; start one with `workflow init`")
        manifest = (
            load_artifact(SourceManifest, ws.source_manifest)
            if ws.source_manifest.is_file()
            else SourceManifest()
        )
        results = []
        for file in files:
            path = normalize_user_path(file, must_exist=True)
            manifest, entry, status = add_source(manifest, path, source_id=source_id)
            results.append((entry, status))
        save_artifact(manifest, ws.source_manifest)
        return results

    results = _guard(run)
    if as_json:
        console.print_json(
            data={
                "manifest": str(ws.source_manifest),
                "sources": [
                    {"id": e.id, "path": e.path, "status": status, "fingerprint": e.fingerprint}
                    for e, status in results
                ],
            }
        )
        return
    for entry, status in results:
        console.print(f"[green]{status}[/green] {escape(entry.id)}  {escape(entry.path)}")
    console.print(f"written {ws.source_manifest}", soft_wrap=True)


@sources_app.command("list")
def sources_list(
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List the workspace's recordings and whether each has a transcript."""
    from social_video.schemas.base import load_artifact
    from social_video.schemas.source import SourceManifest
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)
    manifest = _guard(lambda: load_artifact(SourceManifest, ws.source_manifest))
    rows = [
        {
            "id": e.id,
            "path": e.path,
            "duration": round(e.duration, 3),
            "video": bool(e.video_codec),
            "audio_tracks": e.audio_tracks,
            "transcript": ws.transcript_for(e.id).is_file(),
        }
        for e in manifest.sources
    ]
    if as_json:
        console.print_json(data={"sources": rows})
        return
    for row in rows:
        kind = ("video" if row["video"] else "") + (" audio" if row["audio_tracks"] else "")
        mark = "transcribed" if row["transcript"] else "-"
        console.print(
            f"  {escape(row['id']):24} {row['duration']:8.2f}s  {kind.strip():12} {mark}"
            f"  {escape(row['path'])}",
            soft_wrap=True,
        )
