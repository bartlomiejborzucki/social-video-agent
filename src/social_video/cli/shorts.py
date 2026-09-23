"""Several standalone shorts from one long recording."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.markup import escape
from rich.table import Table

from social_video.cli._apps import (
    shorts_app,
)
from social_video.cli._common import _guard, console, err_console


@shorts_app.command("list")
def shorts_list(
    workspace_dir: Path = typer.Argument(..., help="Workspace holding candidates.json."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show the agent-authored clip candidates, best first."""
    from social_video.shorts import load_candidates
    from social_video.workspace.layout import Workspace

    candidates = _guard(lambda: load_candidates(Workspace.at(workspace_dir)))
    ranked = candidates.ranked()
    if as_json:
        console.print_json(
            json.dumps(
                [
                    {
                        "id": item.id,
                        "topic": item.topic,
                        "start": item.start,
                        "end": item.end,
                        "duration": round(item.duration, 2),
                        "selected": item.selected,
                        "overall": round(item.scores.overall, 3) if item.scores else None,
                        "reason": item.reason,
                    }
                    for item in ranked
                ]
            )
        )
        return
    table = Table(title=f"clip candidates in {candidates.source}", box=None, padding=(0, 2))
    for column in ("id", "span", "duration", "score", "selected", "topic"):
        table.add_column(column, overflow="fold")
    for item in ranked:
        table.add_row(
            item.id,
            f"{item.start:.2f}-{item.end:.2f}s",
            f"{item.duration:.1f}s",
            f"{item.scores.overall:.2f}" if item.scores else "-",
            "yes" if item.selected else "",
            escape(item.topic),
        )
    console.print(table)
    console.print("[dim]Scores are the agent's editorial judgement, not measurements.[/dim]")


@shorts_app.command("create")
def shorts_create(
    workspace_dir: Path = typer.Argument(..., help="Workspace holding candidates.json."),
    only: list[str] | None = typer.Option(
        None, "--only", help="Materialise just this candidate id; repeatable."
    ),
    reframe: str | None = typer.Option(None, "--reframe", help="Framing mode for every clip."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Give each selected candidate its own workspace and EDL. Never re-transcribes."""
    from social_video.schemas.edl import ReframeMode
    from social_video.shorts import materialize_shorts, shorts_summary
    from social_video.workspace.layout import Workspace

    mode: ReframeMode | None = None
    if reframe is not None:
        try:
            mode = ReframeMode(reframe)
        except ValueError:
            supported = ", ".join(item.value for item in ReframeMode)
            err_console.print(
                f"[red]error:[/red] unknown reframe {reframe!r}; expected {supported}"
            )
            raise typer.Exit(1) from None
    index = _guard(
        lambda: materialize_shorts(Workspace.at(workspace_dir), only=only or None, reframe=mode)
    )
    if as_json:
        console.print_json(index.to_json())
        return
    for entry in shorts_summary(index):
        where = escape(str(entry["workspace"]))
        console.print(
            f"[green]{entry['id']}[/green] {entry['duration']}s -> {where}", soft_wrap=True
        )
    console.print(
        f"[dim]{len(index.shorts)} short(s) prepared. Render and QA each one "
        "in its own workspace.[/dim]"
    )
