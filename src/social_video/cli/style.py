"""Reference style: measured by the code, proposed by the agent, accepted by the user."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.markup import escape

from social_video.cli._apps import style_app
from social_video.cli._common import _guard, console


@style_app.command("analyze")
def style_analyze(
    reference: Path = typer.Argument(..., help="A video whose rhythm the edit should match."),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    transcribe: bool = typer.Option(
        False, "--transcribe", help="Also measure speaking pace and the first sentence."
    ),
    model: str = typer.Option("small", "--model"),
    language: str | None = typer.Option(None, "--language"),
    editorial: bool = typer.Option(
        False,
        "--editorial",
        help="Also pull stills (first frame, opening, cuts, last frame) and keep the timed "
        "transcript under context/reference/ for an editorial read.",
    ),
    frames: int = typer.Option(40, "--frames", min=8, help="Most stills for --editorial."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Measure shot length, cut rate, pauses and hook timing of a reference video.

    Writes `context/style-reference.json` and a contact sheet of one frame per
    shot. Only numbers are kept; nothing of the reference reaches the edit, and
    project config is not changed. With `--editorial` it also writes the
    material the agent reads to describe how the video holds attention
    (`context/reference/material.json`); the read itself is checked with
    `style check-analysis`.
    """
    from social_video.analysis.reference import analyze_reference
    from social_video.motion.energy import energy_preset
    from social_video.paths import normalize_user_path
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.config import BrandContract
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        source = normalize_user_path(reference, must_exist=True)
        transcript = None
        if transcribe:
            from social_video.transcribe.base import TranscriptionOptions
            from social_video.transcribe.service import transcribe_source

            # A workspace of its own, so the reference never joins the
            # project's packed transcript.
            transcript = transcribe_source(
                source,
                Workspace.at(ws.cache / "style-reference"),
                options=TranscriptionOptions(model=model, language=language),
            )
        if not editorial:
            result = analyze_reference(
                source, transcript=transcript, sheet=ws.style_reference_sheet
            )
            save_artifact(result, ws.style_reference)
            return result, None
        from social_video.analysis.reference_editorial import prepare_editorial

        transcript_path = None
        if transcript is not None:
            transcript_path = save_artifact(transcript, ws.reference_dir / "transcript.json")
        result, material = prepare_editorial(
            source,
            ws.reference_dir,
            transcript=transcript,
            transcript_path=transcript_path,
            sheet=ws.style_reference_sheet,
            frame_limit=frames,
        )
        save_artifact(result, ws.style_reference)
        save_artifact(material, ws.reference_material)
        return result, material

    result, material = _guard(run)
    current = None
    if ws.brand_contract.is_file():
        brand = load_artifact(BrandContract, ws.brand_contract).brand
        current = energy_preset(brand.motion_energy).name
    rec = result.recommendation

    if as_json:
        payload = result.model_dump(mode="json", exclude_none=True)
        payload["written"] = str(ws.style_reference)
        payload["current_motion_energy"] = current
        if material is not None:
            payload["editorial"] = {
                "material": str(ws.reference_material),
                "frames": len(material.frames),
                "transcript": material.transcript,
                "limitations": material.limitations,
            }
        console.print_json(json.dumps(payload))
        return

    shots = result.shots
    console.print(f"[bold]{escape(Path(result.reference).name)}[/bold]")
    console.print(
        f"  format       {result.width}x{result.height} {result.aspect_ratio}, "
        f"{result.duration:.1f}s"
    )
    console.print(
        f"  shots        {shots.count}, median {shots.median_seconds:.1f}s "
        f"({shots.p25_seconds:.1f}-{shots.p75_seconds:.1f}s), "
        f"{shots.cuts_per_minute:.0f} cuts/min"
    )
    if result.speech is not None:
        speech = result.speech
        line = (
            f"  speech       {speech.sound_ratio:.0%} sound, "
            f"{speech.pauses_per_minute:.0f} pauses/min"
        )
        if speech.words_per_minute is not None:
            line += f", {speech.words_per_minute:.0f} words/min"
        console.print(line)
    energy = rec.motion_energy
    if current and current != energy:
        energy += f" (project: {current})"
    console.print(f"  [green]energy[/green]       {energy}")
    console.print(f"  [green]shot target[/green]  about {rec.target_shot_seconds:g}s")
    console.print(f"  [green]hook within[/green]  {rec.hook_within_seconds:g}s")
    for reason in rec.reasons:
        console.print(f"  - {escape(reason)}")
    if result.contact_sheet:
        console.print(f"  sheet        {result.contact_sheet}", soft_wrap=True)
    console.print(f"[green]written[/green] {ws.style_reference}", soft_wrap=True)
    if material is not None:
        console.print(
            f"[green]editorial[/green] {len(material.frames)} stills in "
            f"{ws.reference_dir / 'frames'}",
            soft_wrap=True,
        )
        for limit in material.limitations:
            console.print(f"  [yellow]limit[/yellow] {escape(limit)}")
        console.print(f"[green]written[/green] {ws.reference_material}", soft_wrap=True)


@style_app.command("check-analysis")
def style_check_analysis(
    analysis_file: Path = typer.Argument(
        None, help="The agent's read (default: context/reference-analysis.json)."
    ),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Check an editorial read of the reference and write it as Markdown.

    Every observation must name a time inside the video or a still that was
    pulled, every hypothesis must cite observations, and every limitation of
    the material is stated. Exits 1 when the read does not hold together.
    """
    from social_video.analysis.reference_editorial import (
        analysis_markdown,
        check_analysis,
        with_material_limits,
    )
    from social_video.errors import ValidationError
    from social_video.fsutil import atomic_write_bytes
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.reference_analysis import ReferenceAnalysis, ReferenceMaterial
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)
    path = analysis_file or ws.reference_analysis

    def run():
        if not ws.reference_material.is_file():
            raise ValidationError(
                "no reference material: run `style analyze REFERENCE --editorial` first"
            )
        material = load_artifact(ReferenceMaterial, ws.reference_material)
        analysis = load_artifact(ReferenceAnalysis, path)
        problems = check_analysis(analysis, material)
        analysis = with_material_limits(analysis, material)
        if not problems:
            save_artifact(analysis, ws.reference_analysis)
            atomic_write_bytes(
                ws.reference_analysis_summary,
                analysis_markdown(analysis, material).encode("utf-8"),
            )
        return problems

    problems = _guard(run)
    if as_json:
        console.print_json(
            json.dumps(
                {
                    "ok": not problems,
                    "problems": problems,
                    "summary": None if problems else str(ws.reference_analysis_summary),
                }
            )
        )
    else:
        for problem in problems:
            console.print(f"[red]problem[/red] {escape(problem)}")
        if not problems:
            console.print(f"[green]written[/green] {ws.reference_analysis_summary}", soft_wrap=True)
    if problems:
        raise typer.Exit(1)
