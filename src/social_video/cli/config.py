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
    motion_energy: str | None = typer.Option(None, "--motion-energy", help="calm, lively, bold."),
    style_pack: str | None = typer.Option(
        None, "--style-pack", help="editorial, bold-social, tech-minimal."
    ),
    label_style: str | None = typer.Option(None, "--label-style", help="chip or scene_frame."),
    highlight: bool | None = typer.Option(
        None, "--karaoke/--no-karaoke", help="Colour the word being spoken."
    ),
    animation: str | None = typer.Option(
        None, "--animation", help="none, pop or box; empty follows motion_energy."
    ),
    emphasis: str | None = typer.Option(
        None, "--emphasis-words", help="Brand words, comma separated."
    ),
    defaults: bool = typer.Option(
        False, "--defaults", help="Do not ask; write the template's values for anything not given."
    ),
) -> None:
    """Create .social-video/config.yaml, asking for the choices that shape every edit.

    Motion energy, style pack, label style, karaoke, word animation and brand
    words are written down explicitly, whether chosen here or taken from the
    template, so no edit runs on a default nobody chose. Without a terminal, or
    with --defaults, nothing is asked.
    """
    import sys

    from social_video.project_config import STYLE_DECISIONS, init_project_config

    given: dict[str, object] = {
        "motion_energy": motion_energy,
        "style_pack": style_pack,
        "label_style": label_style,
        "caption_style.active_word_highlight": highlight,
        "caption_style.animation": animation,
        "caption_style.emphasis_words": (
            [w.strip() for w in emphasis.split(",") if w.strip()] if emphasis is not None else None
        ),
    }
    if not defaults and sys.stdin.isatty():
        asked = {
            "motion_energy": "lively",
            "style_pack": "editorial",
            "label_style": "chip",
            "caption_style.animation": "",
        }
        for key, default in asked.items():
            if given[key] is None:
                given[key] = typer.prompt(STYLE_DECISIONS[key], default=default, show_default=True)
        if given["caption_style.active_word_highlight"] is None:
            given["caption_style.active_word_highlight"] = typer.confirm(
                STYLE_DECISIONS["caption_style.active_word_highlight"], default=False
            )
        if given["caption_style.emphasis_words"] is None:
            words = typer.prompt(
                STYLE_DECISIONS["caption_style.emphasis_words"] + " (comma separated)",
                default="",
                show_default=False,
            )
            given["caption_style.emphasis_words"] = [
                w.strip() for w in words.split(",") if w.strip()
            ]
    choices = {key: value for key, value in given.items() if value is not None}
    path = _guard(lambda: init_project_config(project_root, force=force, choices=choices))
    console.print(f"[green]created[/green] {path}", soft_wrap=True)
    for key in STYLE_DECISIONS:
        how = "chosen" if key in choices else "template"
        console.print(f"  {key}: {escape(repr(_decision(path, key)))} ({how})", soft_wrap=True)


def _decision(path: Path, key: str) -> object:
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    head, _, tail = key.partition(".")
    return (raw.get(head) or {}).get(tail) if tail else raw.get(head)


@config_app.command("validate")
def config_validate(
    project_root: Path = typer.Argument(Path(), help="Target project root."),
    workspace_dir: Path | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Edit workspace to write brand-contract.json into. Without it nothing is written.",
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Validate assets and compile the configuration into an executable contract.

    Names every style decision the config leaves to a default, so a calm,
    karaoke-free edit is never a surprise. Only with --workspace is the
    compiled contract saved; validating never creates an edit folder.
    """
    from social_video.project_config import (
        compile_brand_contract,
        find_project_config,
        implicit_defaults,
    )
    from social_video.workspace.layout import Workspace

    root = project_root.resolve()
    config = find_project_config(root)
    if config is None:
        err_console.print("[red]error:[/red] no .social-video/config.yaml or social-video.yaml")
        raise typer.Exit(1)
    workspace = Workspace.at(workspace_dir) if workspace_dir else None
    contract = _guard(lambda: compile_brand_contract(config, workspace, project_root=root))
    unset = _guard(lambda: implicit_defaults(config))
    payload = {
        "status": "valid",
        "config": str(config),
        "contract": str(workspace.brand_contract) if workspace else None,
        "font": contract.brand.captions.font_family,
        "font_file": contract.resolved_font_file,
        "resolution": f"{contract.output_width}x{contract.output_height}",
        "fps": contract.output_fps,
        "defaults_not_in_config": unset,
    }
    if as_json:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    console.print(f"[green]valid[/green] {config}", soft_wrap=True)
    if workspace is not None:
        console.print(f"[green]compiled[/green] {workspace.brand_contract}", soft_wrap=True)
    else:
        console.print("compiled in memory; pass --workspace to save brand-contract.json")
    for key, value in unset.items():
        console.print(
            f"[yellow]default[/yellow] {key}: {escape(repr(value))} -- not in the config; "
            "write it down if that is the choice",
            soft_wrap=True,
        )


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
