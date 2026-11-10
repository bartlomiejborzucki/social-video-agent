"""Consoles and helpers every command module shares."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterable, Iterator
from pathlib import Path

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


@contextlib.contextmanager
def _compositor_progress() -> Iterator[None]:
    """A progress bar on stderr while Remotion works, when someone is watching.

    It appears with the first progress report, so a command that never
    renders shows nothing. Without a terminal -- an agent, the MCP server, a
    pipe -- there is no bar and the render logs a line per quarter instead;
    stdout is never written to, so `--json` output stays whole.
    """
    from social_video.remotion_node import RenderProgress, progress_to

    if not err_console.is_terminal:
        yield
        return

    from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

    bar: Progress | None = None
    task = None

    def show(progress: RenderProgress) -> None:
        nonlocal bar, task
        if bar is None:
            bar = Progress(
                TextColumn("{task.description}"),
                BarColumn(),
                TextColumn("{task.percentage:>3.0f} %"),
                TimeElapsedColumn(),
                console=err_console,
                transient=True,
            )
            bar.start()
            task = bar.add_task("", total=1.0)
        assert task is not None
        bar.update(task, completed=progress.fraction, description=progress.describe())

    try:
        with progress_to(show):
            yield
    finally:
        if bar is not None:
            bar.stop()


def _guard(fn):
    """Run an operation, turning our own exceptions into clean CLI errors.

    An agent reading stderr should get the actionable message, not a traceback.
    """
    try:
        with _compositor_progress():
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


def overwrites_a_source(destination: Path, sources: Iterable[Path]) -> bool:
    """Whether writing ``destination`` would replace one of the ``sources``.

    Names are compared resolved, and the files themselves when the destination
    exists: on a case-insensitive Windows drive, or through a link, one
    recording answers to two names.
    """
    target = destination.resolve(strict=False)
    for source in sources:
        if target == source.resolve(strict=False):
            return True
        try:
            if destination.exists() and source.exists() and destination.samefile(source):
                return True
        except OSError:
            continue
    return False
