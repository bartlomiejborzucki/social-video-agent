"""Environment checks, and the installers they point at."""

from __future__ import annotations

import json

import typer
from rich.markup import escape
from rich.table import Table

from social_video.cli._apps import (
    app,
)
from social_video.cli._common import _guard, console


@app.command()
def doctor(
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    install_ffmpeg: bool = typer.Option(
        False, "--install-ffmpeg", help="Download a static ffmpeg into the app cache."
    ),
    install_remotion: bool = typer.Option(
        False,
        "--install-remotion",
        help="Install the compositor's locked npm packages and headless browser.",
    ),
) -> None:
    """Check that this machine can actually produce a correct video."""
    from social_video.doctor import run_doctor

    if install_ffmpeg:
        from social_video.ffmpeg.bootstrap import install_static_ffmpeg

        path = install_static_ffmpeg(progress=not as_json)
        console.print(f"[green]ffmpeg installed:[/green] {path}")

    if install_remotion:
        from social_video.remotion_runtime import install_runtime

        runtime = _guard(install_runtime)
        console.print(f"[green]Remotion installed:[/green] {runtime.root}")

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
