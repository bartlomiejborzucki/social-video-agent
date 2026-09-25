"""B-roll from the user's library: found by the code, accepted by the agent."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape

from social_video.cli._apps import broll_app
from social_video.cli._common import _guard, console


@broll_app.command("suggest")
def broll_suggest(
    source: Path = typer.Argument(..., help="Source video the EDL cuts."),
    library_dir: Path = typer.Option(..., "--library", help="Your folder of b-roll clips."),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    model: str = typer.Option("small", "--model"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List clips from your library that match what is said, and where."""
    from social_video.errors import ValidationError
    from social_video.motion.broll import find_broll
    from social_video.pipeline import stage_transcribe
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.edl import EDL
    from social_video.transcribe.base import TranscriptionOptions
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        if not ws.edl.is_file():
            raise ValidationError(f"no EDL at {ws.edl}")
        transcript = stage_transcribe(source, ws, options=TranscriptionOptions(model=model))
        found = find_broll(transcript, load_artifact(EDL, ws.edl), library_dir)
        save_artifact(found, ws.broll_candidates)
        return found

    found = _guard(run)
    if as_json:
        console.print_json(found.to_json())
        return
    if not found.candidates:
        console.print("No clip in the library matches what is said.")
    for c in found.candidates:
        console.print(
            f"  {c.id}  {c.confidence:6} @{c.at:6.2f}s {c.duration:.1f}s  "
            f"{escape(Path(c.file).name)}  ({escape(c.keyword)})"
        )
    console.print(f"\n[green]written[/green] {ws.broll_candidates}", soft_wrap=True)


@broll_app.command("accept")
def broll_accept(
    ids: list[str] = typer.Argument(..., help="Candidate ids, e.g. br-001 br-003."),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
) -> None:
    """Cut the chosen clips in as full-width overlays in edl.json."""
    from social_video.motion.broll import BrollCandidateSet, accept_broll
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.edl import EDL
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        found = load_artifact(BrollCandidateSet, ws.broll_candidates)
        updated, added = accept_broll(load_artifact(EDL, ws.edl), found, ids)
        save_artifact(updated, ws.edl)
        return added

    added = _guard(run)
    console.print(
        f"{len(added)} b-roll overlay(s) added to [green]{ws.edl}[/green]", soft_wrap=True
    )
