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
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Measure shot length, cut rate, pauses and hook timing of a reference video.

    Writes `context/style-reference.json` and a contact sheet of one frame per
    shot. Only numbers are kept; nothing of the reference reaches the edit, and
    project config is not changed.
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
        result = analyze_reference(source, transcript=transcript, sheet=ws.style_reference_sheet)
        save_artifact(result, ws.style_reference)
        return result

    result = _guard(run)
    current = None
    if ws.brand_contract.is_file():
        brand = load_artifact(BrandContract, ws.brand_contract).brand
        current = energy_preset(brand.motion_energy).name
    rec = result.recommendation

    if as_json:
        payload = result.model_dump(mode="json", exclude_none=True)
        payload["written"] = str(ws.style_reference)
        payload["current_motion_energy"] = current
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
