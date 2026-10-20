"""Montage briefs and the content-first opening."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape

from social_video.cli._apps import app, brief_app
from social_video.cli._common import _guard, console


@brief_app.command("import")
def brief_import(
    file: Path = typer.Argument(
        ...,
        help="A brief as text, the package's pakiet_sm JSON, or the month's posts .docx "
        "(choose the reel with --match; tracked deletions are left out).",
    ),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    entry: int | None = typer.Option(None, "--entry", help="Which reel of the package (from 0)."),
    match: str | None = typer.Option(
        None, "--match", help="Choose the reel whose title (or text) has this."
    ),
    labels: bool = typer.Option(
        False, "--labels", help="Add the brief's short on-screen texts to motion-plan.json."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Make the brief the edit's override: first caption, labels and cover text."""
    from social_video.editorial.brief import load_brief, overrides
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan
    from social_video.schemas.plan import EditPlan
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        brief = load_brief(file, entry=entry, match=match)
        save_artifact(brief, ws.brief)
        lines = overrides(brief)
        if ws.edit_plan.is_file():
            plan = load_artifact(EditPlan, ws.edit_plan)
            kept = [line for line in plan.user_overrides if not line.startswith("brief:")]
            save_artifact(plan.model_copy(update={"user_overrides": kept + lines}), ws.edit_plan)
        if labels and brief.labels:
            motion = (
                load_artifact(MotionPlan, ws.motion_plan)
                if ws.motion_plan.is_file()
                else MotionPlan(rationale="On-screen labels from the montage brief.")
            )
            elements = [e for e in motion.elements if e.type is not MotionElementType.LABEL]
            elements += [
                MotionElement(
                    type=MotionElementType.LABEL, start=label.start, end=label.end,
                    text=label.text, reason="On-screen text from the montage brief.",
                )
                for label in brief.labels
            ]  # fmt: skip
            updated = motion.model_copy(
                update={"elements": sorted(elements, key=lambda e: e.start)}
            )
            save_artifact(MotionPlan.model_validate(updated.model_dump()), ws.motion_plan)
        return brief, lines

    brief, lines = _guard(run)
    if as_json:
        console.print_json(brief.to_json())
        return
    console.print(f"[green]written[/green] {ws.brief}", soft_wrap=True)
    for line in lines:
        console.print(f"  {escape(line)}", soft_wrap=True)
    if not ws.edit_plan.is_file():
        console.print("  no edit-plan.json yet: the overrides are added when you write it")


@brief_app.command("show")
def brief_show(workspace_dir: Path = typer.Option(..., "--workspace", "-w")) -> None:
    """Print the brief this edit was given."""
    from social_video.schemas.base import load_artifact
    from social_video.schemas.brief import Brief
    from social_video.workspace.layout import Workspace

    console.print_json(
        _guard(lambda: load_artifact(Brief, Workspace.at(workspace_dir).brief)).to_json()
    )


@app.command("opening-qa")
def opening_qa(
    workspace_dir: Path = typer.Argument(..., help="Edit workspace."),
    video: Path | None = typer.Option(None, "--video", help="Default: final, else the preview."),
    first_frame_note: str = typer.Option(
        "", "--first-frame-note", help="One sentence on what frame 0 shows, after looking at it."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Check the opening: scene at frame 0, first caption at 0.0 s, no card, no silence."""
    from social_video.errors import ValidationError
    from social_video.motion.film import load_registry
    from social_video.pipeline import load_workspace_artifacts, resolve_caption_track
    from social_video.qa.opening import check_opening
    from social_video.schemas.base import load_artifact
    from social_video.schemas.brief import Brief
    from social_video.schemas.config import BrandContract, OpeningPolicy
    from social_video.schemas.motion import MotionPlan
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        sources, edl = load_workspace_artifacts(ws)
        target = video or next(
            (p for p in (ws.final / "final.mp4", ws.previews / "preview.mp4") if p.is_file()), None
        )
        if target is None:
            raise ValidationError("no render to check; render first or pass --video")
        contract = (
            load_artifact(BrandContract, ws.brand_contract) if ws.brand_contract.is_file() else None
        )
        captions = resolve_caption_track(Path(edl.captions))[0] if edl.captions else None
        plan = load_artifact(MotionPlan, ws.motion_plan) if ws.motion_plan.is_file() else None
        brief = load_artifact(Brief, ws.brief) if ws.brief.is_file() else None
        return check_opening(
            target, edl, plan, captions,
            contract.opening if contract else OpeningPolicy(),
            sources=sources, film_segments=load_registry(ws).segments,
            brief_first_text=brief.first_cue_text if brief else "",
            first_frame_note=first_frame_note, analysis_dir=ws.analysis,
        )  # fmt: skip

    report = _guard(run)
    if as_json:
        console.print_json(report.to_json())
    else:
        verdict = "[green]ready[/green]" if report.ready else "[red]not ready[/red]"
        console.print(f"opening ({report.policy}): {verdict}")
        console.print(f"  first frame: {escape(report.first_frame_note)}", soft_wrap=True)
        console.print(
            f"  first caption at {report.first_cue_start_s} s: {escape(report.first_cue_text)}"
        )
        console.print(f"  leading silence {report.leading_silence_s:.2f} s")
        for issue in report.issues:
            console.print(f"  [yellow]fix[/yellow] {escape(issue)}", soft_wrap=True)
        if report.variant:
            console.print(f"  {escape(report.variant)}", soft_wrap=True)
        console.print(f"[green]written[/green] {ws.opening_qa}", soft_wrap=True)
    if not report.ready:
        raise typer.Exit(1)


@app.command("reel-check")
def reel_check(
    workspace_dir: Path = typer.Argument(..., help="Edit workspace."),
    video: Path | None = typer.Option(None, "--video", help="Default: final, else the preview."),
    platform: list[str] = typer.Option([], "--platform", help="Destination (repeat)."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Short-form practices that measure: hook speed, length, dead air, holds, captions."""
    from social_video.errors import ValidationError
    from social_video.pipeline import load_workspace_artifacts, resolve_caption_track
    from social_video.profiles import load_platform
    from social_video.qa.reel import check_reel
    from social_video.schemas.base import load_artifact
    from social_video.schemas.config import BrandContract
    from social_video.schemas.motion import MotionPlan
    from social_video.schemas.publish import PublishMetadata
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        _sources, edl = load_workspace_artifacts(ws)
        target = video or next(
            (p for p in (ws.final / "final.mp4", ws.previews / "preview.mp4") if p.is_file()), None
        )
        if target is None:
            raise ValidationError("no render to check; render first or pass --video")
        names = platform or (
            load_artifact(BrandContract, ws.brand_contract).target_platforms
            if ws.brand_contract.is_file()
            else []
        )
        return check_reel(
            target,
            edl,
            captions=resolve_caption_track(Path(edl.captions))[0] if edl.captions else None,
            plan=load_artifact(MotionPlan, ws.motion_plan) if ws.motion_plan.is_file() else None,
            platforms=[load_platform(name) for name in names],
            publish=(
                load_artifact(PublishMetadata, ws.publish_metadata)
                if ws.publish_metadata.is_file()
                else None
            ),
            analysis_dir=ws.analysis,
        )

    result = _guard(run)
    if as_json:
        console.print_json(result.to_json())
        return
    console.print(f"reel check {result.passed}/{result.total} (advisory)")
    for check in result.report.checks:
        mark = "[green]ok[/green]  " if check.passed else "[yellow]warn[/yellow]"
        console.print(f"  {mark} {escape(check.name)}: {escape(check.message)}", soft_wrap=True)
    console.print(f"[green]written[/green] {ws.analysis / 'reel-check.md'}", soft_wrap=True)
