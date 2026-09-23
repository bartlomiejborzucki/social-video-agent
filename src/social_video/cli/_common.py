"""Consoles and helpers every command module shares."""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.markup import escape

from social_video.errors import SocialVideoError

console = Console()
err_console = Console(stderr=True)


def _print_qa(report) -> None:
    console.print("[bold]QA[/bold]")
    for check in report.checks:
        if check.passed:
            mark = "[green]ok[/green]  "
        elif check.accepted:
            mark = "[cyan]accepted[/cyan]"
        elif check.severity.value == "error":
            mark = "[red]FAIL[/red]"
        else:
            mark = "[yellow]warn[/yellow]"
        console.print(f"  {mark} {escape(check.name)}: {escape(check.message)}")
    if report.status == "passed":
        console.print("[green]passed[/green]")
    elif report.status == "passed_with_warnings":
        console.print("[yellow]passed_with_warnings[/yellow]")
    else:
        console.print(f"[red]{len(report.errors)} problem(s)[/red]")
        if report.exhausted:
            console.print(
                "[yellow]repair budget exhausted; reporting rather than retrying[/yellow]"
            )


def _guard(fn):
    """Run an operation, turning our own exceptions into clean CLI errors.

    An agent reading stderr should get the actionable message, not a traceback.
    """
    try:
        return fn()
    except (SocialVideoError, ValueError, RuntimeError) as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except FileNotFoundError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except OSError as exc:
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            raise
        err_console.print(f"[red]error:[/red] file operation failed: {exc}")
        raise typer.Exit(1) from exc
