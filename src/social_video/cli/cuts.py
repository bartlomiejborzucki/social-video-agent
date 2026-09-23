"""Cut candidates: found by the code, accepted by the agent."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape

from social_video.cli._apps import cuts_app
from social_video.cli._common import _guard, console


@cuts_app.command("find")
def cuts_find(
    source: Path = typer.Argument(..., help="Source video, as passed to `plan`."),
    workspace_dir: Path | None = typer.Option(None, "--workspace", "-w"),
    profile: str = typer.Option("talking-head", "--profile", "-p"),
    model: str = typer.Option("small", "--model", help="Transcription model size."),
    language: str | None = typer.Option(None, "--language"),
    audio_track: int = typer.Option(0, "--audio-track"),
    backend: str | None = typer.Option(None, "--backend"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List every stumble visible from timing, with an id and a confidence.

    Nothing is changed. Read each candidate against the transcript, then pass
    the ids you agree with to `cuts accept`.
    """
    from social_video.editorial.cuts import find_cut_candidates
    from social_video.pipeline import stage_transcribe
    from social_video.profiles import load_profile
    from social_video.schemas.base import save_artifact
    from social_video.transcribe.base import TranscriptionOptions
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir) if workspace_dir else Workspace.for_source(source)
    prof = _guard(lambda: load_profile(profile))
    options = TranscriptionOptions(model=model, language=language, audio_track=audio_track)
    transcript = _guard(lambda: stage_transcribe(source, ws, options=options, backend=backend))
    found = find_cut_candidates(transcript, prof)
    save_artifact(found, ws.cut_candidates)

    if as_json:
        console.print_json(found.to_json())
        return
    if not found.candidates:
        console.print("No stumbles found from timing alone.")
    for candidate in found.candidates:
        colour = "green" if candidate.confidence.value == "high" else "yellow"
        console.print(
            f"  {candidate.id}  [{colour}]{candidate.confidence.value:6}[/{colour}] "
            f"{candidate.kind.value:11} [{candidate.start:7.2f}-{candidate.end:7.2f}] "
            f"{escape(candidate.reason)}"
            + (f'  "{escape(candidate.quote)}"' if candidate.quote else "")
        )
    console.print(f"\n[green]written[/green] {ws.cut_candidates}", soft_wrap=True)


@cuts_app.command("accept")
def cuts_accept(
    ids: list[str] = typer.Argument(None, help="Candidate ids to accept, e.g. cut-001 cut-004."),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    kind: list[str] = typer.Option(
        [], "--kind", help="Accept every candidate of this kind (repeatable)."
    ),
    confidence: str | None = typer.Option(
        None, "--confidence", help="With --kind, only candidates at this confidence."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Add the chosen candidates to edit-plan.json as drops, with their reasons."""
    from social_video.editorial.cuts import accept_cuts
    from social_video.errors import ValidationError
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.plan import CutCandidateSet, EditPlan
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        if not ws.cut_candidates.is_file():
            raise ValidationError(f"no cut candidates at {ws.cut_candidates}; run `cuts find`")
        if not ws.edit_plan.is_file():
            raise ValidationError(f"no edit plan at {ws.edit_plan}; run `plan` first")
        found = load_artifact(CutCandidateSet, ws.cut_candidates)
        plan = load_artifact(EditPlan, ws.edit_plan)
        chosen = list(ids or [])
        chosen += [
            c.id
            for c in found.candidates
            if c.kind.value in kind and (confidence is None or c.confidence.value == confidence)
        ]
        if not chosen and kind and not ids:
            # A filter that matches nothing is an answer, not a mistake.
            return []
        added = accept_cuts(plan, found, chosen)
        save_artifact(plan, ws.edit_plan)
        return added

    added = _guard(run)
    if as_json:
        console.print_json(data=[item.model_dump(mode="json") for item in added])
        return
    for item in added:
        console.print(
            f"  [yellow]drop[/yellow] [{item.start:7.2f}-{item.end:7.2f}] {escape(item.reason)}"
        )
    console.print(
        f"\n{len(added)} cut(s) added to [green]{ws.edit_plan}[/green]. "
        "`social-video-agent compile SOURCE -w WORKSPACE --force` rebuilds edl.json "
        "with them removed.",
        soft_wrap=True,
    )
