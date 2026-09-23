"""Target-project context and the persisted multi-stage workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.markup import escape

from social_video.cli._apps import (
    context_app,
    workflow_app,
)
from social_video.cli._common import _guard, console


@context_app.command("inspect")
def context_inspect(
    project_root: Path = typer.Argument(Path(), help="Target project, not skill root."),
    workspace_dir: Path | None = typer.Option(None, "--workspace", "-w"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Discover relevant local guidance without recursively ingesting the project."""
    from social_video.project_context import discover_project_context, resolve_project_root
    from social_video.workspace.layout import Workspace

    root = _guard(lambda: resolve_project_root(project_root))
    workspace = Workspace.at(workspace_dir or root / "edit")
    context, sources = _guard(lambda: discover_project_context(root, workspace))
    _print_context(context, sources, as_json=as_json)


@context_app.command("refresh")
def context_refresh(
    project_root: Path = typer.Argument(Path(), help="Target project, not skill root."),
    workspace_dir: Path | None = typer.Option(None, "--workspace", "-w"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Force a new bounded scan and replace cached project-context artifacts."""
    from social_video.project_context import discover_project_context, resolve_project_root
    from social_video.workspace.layout import Workspace

    root = _guard(lambda: resolve_project_root(project_root))
    workspace = Workspace.at(workspace_dir or root / "edit")
    context, sources = _guard(lambda: discover_project_context(root, workspace, refresh=True))
    _print_context(context, sources, as_json=as_json)


@workflow_app.command("init")
def workflow_init(
    source: Path = typer.Argument(..., help="Source media; it remains immutable."),
    workspace_dir: Path | None = typer.Option(None, "--workspace", "-w"),
    project_root: Path | None = typer.Option(None, "--project-root"),
    model_budget: str = typer.Option("balanced", "--model-budget"),
    workflow_mode: str = typer.Option("guided", "--workflow-mode"),
    renderer: str = typer.Option("remotion", "--renderer"),
    remotion_license: str | None = typer.Option(
        None,
        "--remotion-license",
        help="Required for Remotion: free_license_eligible or company_license_confirmed.",
    ),
    quick: bool = typer.Option(False, "--quick", help="Continuous workflow on current model."),
    refresh_context: bool = typer.Option(False, "--refresh-context"),
    language: str = typer.Option("en", "--language"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Create Stage 0/1 state and context. Never renders video."""
    from social_video.paths import normalize_user_path
    from social_video.pipeline import stage_ingest
    from social_video.schemas.workflow import (
        ModelBudget,
        RemotionLicenseAttestation,
        Renderer,
        WorkflowMode,
    )
    from social_video.workflow import create_workflow, workflow_status
    from social_video.workspace.layout import Workspace

    normalized_source = _guard(lambda: normalize_user_path(source, must_exist=True))
    workspace = (
        Workspace.at(workspace_dir) if workspace_dir else Workspace.for_source(normalized_source)
    )
    budget = _guard(lambda: ModelBudget(model_budget))
    mode = WorkflowMode.CONTINUOUS if quick else _guard(lambda: WorkflowMode(workflow_mode))
    selected_renderer = _guard(lambda: Renderer(renderer))
    attestation = (
        _guard(lambda: RemotionLicenseAttestation(remotion_license)) if remotion_license else None
    )
    state = _guard(
        lambda: create_workflow(
            [normalized_source],
            workspace,
            project_root=project_root,
            model_budget=budget,
            workflow_mode=mode,
            renderer=selected_renderer,
            remotion_license_attestation=attestation,
            refresh_context=refresh_context,
        )
    )
    _guard(lambda: stage_ingest(normalized_source, workspace))
    payload = workflow_status(state, language=language)
    _print_workflow(payload, as_json=as_json)


@workflow_app.command("status")
def workflow_show_status(
    workspace_dir: Path = typer.Argument(Path(), help="Edit workspace."),
    language: str = typer.Option("en", "--language"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Report persisted state, missing artifacts, and the recommended handoff."""
    from social_video.workflow import load_workflow, workflow_status
    from social_video.workspace.layout import Workspace

    state = _guard(lambda: load_workflow(Workspace.at(workspace_dir)))
    _print_workflow(workflow_status(state, language=language), as_json=as_json)


@workflow_app.command("resume")
def workflow_resume(
    workspace_dir: Path = typer.Argument(Path(), help="Edit workspace."),
    language: str = typer.Option("en", "--language"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Resume from files only; equivalent to workflow status."""
    workflow_show_status(workspace_dir, language, as_json)


@workflow_app.command("complete")
def workflow_complete(
    stage: int = typer.Argument(..., min=1, max=5),
    workspace_dir: Path = typer.Option(Path(), "--workspace", "-w"),
    language: str = typer.Option("en", "--language"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Validate the current stage artifacts, persist completion, and stop/handoff."""
    from social_video.schemas.workflow import WorkflowStage
    from social_video.workflow import advance_workflow, workflow_status
    from social_video.workspace.layout import Workspace

    stages = {
        1: WorkflowStage.EDITORIAL_PLAN,
        2: WorkflowStage.EXECUTION,
        3: WorkflowStage.EDITORIAL_REVIEW,
        4: WorkflowStage.FINALIZATION,
        5: WorkflowStage.DELIVERY,
    }
    state = _guard(lambda: advance_workflow(Workspace.at(workspace_dir), stages[stage]))
    _print_workflow(workflow_status(state, language=language), as_json=as_json)


@workflow_app.command("renderer")
def workflow_renderer(
    renderer: str = typer.Argument(..., help="remotion or ffmpeg."),
    workspace_dir: Path = typer.Option(Path(), "--workspace", "-w"),
    remotion_license: str | None = typer.Option(
        None,
        "--remotion-license",
        help="free_license_eligible or company_license_confirmed, if none is stored.",
    ),
    language: str = typer.Option("en", "--language"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Switch this workflow's renderer, including a legacy FFmpeg workspace.

    Moving to Remotion needs the licence declaration; a workflow past Stage 2
    returns to it, because the preview must be rendered again.
    """
    from social_video.errors import ValidationError
    from social_video.schemas.workflow import RemotionLicenseAttestation, Renderer
    from social_video.workflow import set_renderer, workflow_status
    from social_video.workspace.layout import Workspace

    def run():
        try:
            chosen = Renderer(renderer)
            attestation = RemotionLicenseAttestation(remotion_license) if remotion_license else None
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        return set_renderer(
            Workspace.at(workspace_dir), chosen, remotion_license_attestation=attestation
        )

    state = _guard(run)
    _print_workflow(workflow_status(state, language=language), as_json=as_json)


def _print_context(context, sources, *, as_json: bool) -> None:
    payload = {
        "target_project_root": context.target_project_root,
        "cache_status": context.cache_status,
        "explicit_config": context.explicit_config,
        "project_context": context.model_dump(mode="json", exclude={"schema_version"}),
        "sources": [
            {
                "path": item.path,
                "type": item.source_type,
                "confidence": item.confidence.value,
                "relevance": item.relevance,
            }
            for item in sources.sources
        ],
        "conflicts": context.conflicts,
        "unknowns": context.unknowns,
    }
    if as_json:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    console.print(f"[bold]Project context[/bold]  {escape(context.target_project_root)}")
    if sources.sources:
        for item in sources.sources[:10]:
            console.print(
                f"  - {escape(item.path)} ({item.confidence.value}, {item.relevance}/100)"
            )
    else:
        console.print("  No brandbook or project-specific video guidance found; use defaults.")
    if context.claims:
        console.print("[bold]Explicit facts[/bold]")
        for claim in context.claims[:5]:
            console.print(
                f"  - {escape(claim.category)}.{escape(claim.key)} = "
                f"{escape(str(claim.value))} ({escape(claim.source)})"
            )
    console.print(f"[green]{context.cache_status}[/green]")


def _print_workflow(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    polish = payload.get("language") == "pl"
    console.print(f"[bold]{escape(payload['current_stage'])}[/bold]")
    if payload.get("renderer"):
        console.print(f"Renderer: [cyan]{escape(payload['renderer'])}[/cyan]")
    if payload.get("remotion_license_attestation"):
        license_label = "Deklaracja licencji Remotion" if polish else "Remotion license declaration"
        source = payload.get("remotion_license_source")
        suffix = f" ({escape(source)})" if source else ""
        console.print(f"{license_label}: {escape(payload['remotion_license_attestation'])}{suffix}")
        if source == "cli_flag":
            hint = (
                "Zapisz deklarację dla projektu, aby kolejne sesje jej nie powtarzały: "
                "`social-video-agent remotion-license attest DECLARATION --accept-terms`"
                if polish
                else "Record it for the project so later sessions reuse it: "
                "`social-video-agent remotion-license attest DECLARATION --accept-terms`"
            )
            console.print(f"[dim]{escape(hint)}[/dim]", soft_wrap=True)
    if payload["missing_artifacts"]:
        missing_label = "Brakujące artefakty etapu:" if polish else "Missing for this stage:"
        console.print(f"[yellow]{missing_label}[/yellow]")
        for path in payload["missing_artifacts"]:
            console.print(f"  - {escape(path)}")
    if payload["handoff_required"]:
        model_label = "Zalecane modele" if polish else "Recommended models"
        effort_label = "Poziom rozumowania" if polish else "Reasoning"
        console.print(f"[bold]{model_label}[/bold]")
        models = payload.get("next_models") or {"openai": payload["next_model"]}
        provider_labels = {"openai": "OpenAI", "claude": "Claude"}
        for provider, model in models.items():
            label = provider_labels.get(provider, provider.title())
            console.print(f"  {label}: [cyan]{escape(model)}[/cyan]")
        console.print(f"{effort_label}: {escape(payload['reasoning_effort'])}")
    else:
        console.print(
            "Kontynuuj bieżącym modelem (tryb continuous)."
            if polish
            else "Continue with the current model (continuous mode)."
        )
    console.print(escape(payload["reason"]))
    if payload["next_prompt"]:
        if payload["handoff_required"]:
            label = "Po zmianie modelu wyślij" if polish else "After switching, send"
        else:
            label = "Kontynuuj poleceniem" if polish else "Continue with"
        console.print(f'{label}: "{escape(payload["next_prompt"])}"')
