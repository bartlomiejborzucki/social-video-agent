"""Project branding: initialise, validate and migrate ``.social-video/config.yaml``."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.markup import escape

from social_video.cli._apps import (
    config_app,
)
from social_video.cli._common import _guard, console, err_console
from social_video.errors import SocialVideoError


@config_app.command("init")
def config_init(
    project_root: Path = typer.Argument(Path(), help="Target project root."),
    force: bool = typer.Option(False, "--force", help="Replace an existing config."),
) -> None:
    """Create a documented .social-video/config.yaml template."""
    from social_video.project_config import init_project_config

    path = _guard(lambda: init_project_config(project_root, force=force))
    console.print(f"[green]created[/green] {path}", soft_wrap=True)


@config_app.command("validate")
def config_validate(
    project_root: Path = typer.Argument(Path(), help="Target project root."),
    workspace_dir: Path | None = typer.Option(None, "--workspace", "-w"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Validate assets and compile configuration into an executable contract."""
    from social_video.project_config import compile_brand_contract, find_project_config
    from social_video.workspace.layout import Workspace

    root = project_root.resolve()
    config = find_project_config(root)
    if config is None:
        err_console.print("[red]error:[/red] no .social-video/config.yaml or social-video.yaml")
        raise typer.Exit(1)
    workspace = Workspace.at(workspace_dir or root / "edit")
    contract = _guard(lambda: compile_brand_contract(config, workspace, project_root=root))
    payload = {
        "status": "valid",
        "config": str(config),
        "contract": str(workspace.brand_contract),
        "font": contract.brand.captions.font_family,
        "font_file": contract.resolved_font_file,
        "resolution": f"{contract.output_width}x{contract.output_height}",
        "fps": contract.output_fps,
    }
    if as_json:
        console.print_json(json.dumps(payload))
    else:
        console.print(f"[green]valid[/green] {config}")
        console.print(f"[green]compiled[/green] {workspace.brand_contract}")


@config_app.command("migrate")
def config_migrate(
    project_root: Path = typer.Argument(Path(), help="Target project root."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Report every pre-0.4 value that still needs a human decision."""
    import yaml

    from social_video.config_migration import LEGACY_ALIASES, plan_migration
    from social_video.project_config import find_project_config

    root = project_root.resolve()
    config = find_project_config(root)
    if config is None:
        err_console.print("[red]error:[/red] no .social-video/config.yaml or social-video.yaml")
        raise typer.Exit(1)

    def _plan():
        raw = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise SocialVideoError(f"project video config must be a mapping: {config}")
        return raw, plan_migration(raw)

    raw, (_, issues) = _guard(_plan)
    renames = {
        legacy: current
        for legacy, current in LEGACY_ALIASES.items()
        if legacy in raw and current not in raw
    }
    payload = {
        "config": str(config),
        "status": "needs_decisions" if issues else "ready",
        "automatic_renames": renames,
        "issues": [
            {
                "field": issue.field,
                "value": issue.value,
                "reason": issue.reason,
                "instruction": issue.instruction,
            }
            for issue in issues
        ],
    }
    if as_json:
        console.print_json(json.dumps(payload, default=str))
    else:
        for legacy, current in renames.items():
            console.print(f"[cyan]rename[/cyan] {legacy} -> {current} (applied automatically)")
        for issue in issues:
            value = escape(repr(issue.value))
            console.print(f"[yellow]decide[/yellow] {escape(issue.field)}: {value}")
            console.print(f"  why: {escape(issue.reason)}", soft_wrap=True)
            console.print(f"  fix: {escape(issue.instruction)}", soft_wrap=True)
        if not issues:
            console.print(f"[green]ready[/green] {config} needs no manual migration")
    if issues:
        raise typer.Exit(1)
