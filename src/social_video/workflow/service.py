"""Create, validate, advance, and resume workflow state without chat history."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from social_video.errors import ValidationError
from social_video.paths import normalize_user_path
from social_video.project_context import discover_project_context, resolve_project_root
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.editorial_qa import EditorialQA
from social_video.schemas.edl import EDL
from social_video.schemas.plan import EditPlan
from social_video.schemas.qa import QAReport
from social_video.schemas.workflow import ModelBudget, WorkflowMode, WorkflowStage, WorkflowState
from social_video.workspace.layout import Workspace

STAGE_ORDER = (
    WorkflowStage.EDITORIAL_PLAN,
    WorkflowStage.EXECUTION,
    WorkflowStage.EDITORIAL_REVIEW,
    WorkflowStage.FINALIZATION,
    WorkflowStage.DELIVERY,
)


def create_workflow(
    source_media: list[str | Path],
    workspace: Workspace,
    *,
    project_root: str | Path | None = None,
    model_budget: ModelBudget = ModelBudget.BALANCED,
    workflow_mode: WorkflowMode = WorkflowMode.GUIDED,
    refresh_context: bool = False,
) -> WorkflowState:
    workspace.ensure()
    target = resolve_project_root(project_root)
    context, _ = discover_project_context(target, workspace, refresh=refresh_context)
    configured_budget = context.config.get("model_budget")
    configured_mode = context.config.get("workflow_mode")
    if configured_budget and model_budget is ModelBudget.BALANCED:
        model_budget = ModelBudget(str(configured_budget))
    if configured_mode and workflow_mode is WorkflowMode.GUIDED:
        workflow_mode = WorkflowMode(str(configured_mode))
    now = _now()
    state = WorkflowState(
        target_project_root=str(target),
        workspace=str(workspace.root),
        source_media=[str(normalize_user_path(item, must_exist=True)) for item in source_media],
        model_budget=model_budget,
        workflow_mode=workflow_mode,
        project_context_path=str(workspace.project_context),
        edit_plan_path=str(workspace.edit_plan),
        edl_path=str(workspace.edl),
        preview_path=str(workspace.previews / "preview.mp4"),
        technical_qa_path=str(workspace.technical_qa),
        editorial_qa_path=str(workspace.editorial_qa),
        final_output_path=str(workspace.final / "final.mp4"),
        delivery_manifest_path=str(workspace.delivery_manifest),
        created_at=now,
        updated_at=now,
        **_recommendation(WorkflowStage.EDITORIAL_PLAN, model_budget, workflow_mode),
    )
    save_artifact(state, workspace.workflow_state)
    return state


def load_workflow(workspace: Workspace) -> WorkflowState:
    return load_artifact(WorkflowState, workspace.workflow_state)


def advance_workflow(workspace: Workspace, completed: WorkflowStage) -> WorkflowState:
    state = load_workflow(workspace)
    if completed is WorkflowStage.COMPLETE:
        raise ValidationError("complete is not an executable workflow stage")
    if state.current_stage is not completed:
        raise ValidationError(
            f"cannot complete {completed.value}; current stage is {state.current_stage.value}"
        )
    _validate_stage_artifacts(state, completed)
    if completed not in state.completed_stages:
        state.completed_stages.append(completed)
    index = STAGE_ORDER.index(completed)
    next_stage = STAGE_ORDER[index + 1] if index + 1 < len(STAGE_ORDER) else WorkflowStage.COMPLETE
    state.current_stage = next_stage
    state.updated_at = _now()
    for key, value in _recommendation(next_stage, state.model_budget, state.workflow_mode).items():
        setattr(state, key, value)
    save_artifact(state, workspace.workflow_state)
    return state


def workflow_status(state: WorkflowState, *, language: str = "en") -> dict[str, Any]:
    missing = _missing_for_stage(state, state.current_stage)
    prompt = _next_prompt(state.current_stage, language)
    language_key = "pl" if language.casefold().startswith("pl") else "en"
    reasons = _routing()["reasons"][language_key]
    reason = (
        "Etapowy workflow jest zakończony."
        if state.current_stage is WorkflowStage.COMPLETE and language_key == "pl"
        else "The staged workflow is complete."
        if state.current_stage is WorkflowStage.COMPLETE
        else reasons[state.current_stage.value]
    )
    return {
        "language": language_key,
        "current_stage": state.current_stage.value,
        "completed_stages": [stage.value for stage in state.completed_stages],
        "next_model_tier": state.recommended_next_model_tier,
        "next_model": state.recommended_next_model_name,
        "reasoning_effort": state.recommended_reasoning_effort,
        "reason": reason,
        "handoff_required": state.handoff_required,
        "next_prompt": prompt,
        "required_artifacts": _required_paths(state, state.current_stage),
        "missing_artifacts": missing,
        "workspace": state.workspace,
        "target_project_root": state.target_project_root,
    }


def _routing() -> dict[str, Any]:
    resource = files("social_video.workflow").joinpath("model-routing.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _recommendation(
    stage: WorkflowStage, budget: ModelBudget, mode: WorkflowMode
) -> dict[str, Any]:
    if stage is WorkflowStage.COMPLETE:
        return {
            "recommended_next_model_tier": "none",
            "recommended_next_model_name": "none",
            "recommended_reasoning_effort": "none",
            "recommendation_reason": "The staged workflow is complete.",
            "handoff_required": False,
        }
    routing = _routing()
    tier = routing["stages"][budget.value][stage.value]
    model = routing["tiers"][tier]
    continuous = mode is WorkflowMode.CONTINUOUS
    return {
        "recommended_next_model_tier": tier,
        "recommended_next_model_name": "current model" if continuous else model["name"],
        "recommended_reasoning_effort": model["reasoning_effort"],
        "recommendation_reason": routing["reasons"]["en"][stage.value],
        "handoff_required": not continuous,
    }


def _validate_stage_artifacts(state: WorkflowState, stage: WorkflowStage) -> None:
    paths = _required_paths(state, stage)
    missing = [path for path in paths if not Path(path).is_file()]
    if missing:
        raise ValidationError(
            f"cannot complete {stage.value}; missing required artifact(s): " + ", ".join(missing)
        )
    if stage is WorkflowStage.EDITORIAL_PLAN:
        load_artifact(EditPlan, state.edit_plan_path)
    elif stage is WorkflowStage.EXECUTION:
        load_artifact(EDL, state.edl_path)
        report = load_artifact(QAReport, state.technical_qa_path)
        if not report.passed:
            raise ValidationError("cannot complete Stage 2; technical QA failed")
    elif stage is WorkflowStage.EDITORIAL_REVIEW:
        load_artifact(EditorialQA, state.editorial_qa_path)
    elif stage is WorkflowStage.FINALIZATION:
        report = load_artifact(QAReport, state.technical_qa_path)
        if not report.passed:
            raise ValidationError("cannot complete Stage 4; technical QA failed")
    elif stage is WorkflowStage.DELIVERY:
        try:
            manifest = json.loads(Path(state.delivery_manifest_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"invalid delivery manifest: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ValidationError("invalid delivery manifest: root must be an object")


def _required_paths(state: WorkflowState, stage: WorkflowStage) -> list[str]:
    if stage is WorkflowStage.EDITORIAL_PLAN:
        return [state.project_context_path, state.edit_plan_path]
    if stage is WorkflowStage.EXECUTION:
        return [state.edl_path, state.preview_path, state.technical_qa_path]
    if stage is WorkflowStage.EDITORIAL_REVIEW:
        return [state.editorial_qa_path]
    if stage is WorkflowStage.FINALIZATION:
        return [state.final_output_path, state.technical_qa_path]
    if stage is WorkflowStage.DELIVERY:
        return [state.delivery_manifest_path]
    return []


def _missing_for_stage(state: WorkflowState, stage: WorkflowStage) -> list[str]:
    return [path for path in _required_paths(state, stage) if not Path(path).is_file()]


def _next_prompt(stage: WorkflowStage, language: str) -> str:
    polish = language.casefold().startswith("pl")
    prompts = {
        WorkflowStage.EDITORIAL_PLAN: (
            "Kontynuuj social-video-agent z Etapem 1."
            if polish
            else "Continue social-video-agent with Stage 1."
        ),
        WorkflowStage.EXECUTION: (
            "Kontynuuj social-video-agent z Etapem 2."
            if polish
            else "Continue social-video-agent with Stage 2."
        ),
        WorkflowStage.EDITORIAL_REVIEW: (
            "Przejrzyj podgląd social-video w Etapie 3."
            if polish
            else "Review the social-video preview with Stage 3."
        ),
        WorkflowStage.FINALIZATION: (
            "Kontynuuj finalizację w Etapie 4."
            if polish
            else "Continue social-video-agent with Stage 4."
        ),
        WorkflowStage.DELIVERY: (
            "Utwórz warianty dostawy w Etapie 5."
            if polish
            else "Create delivery variants with Stage 5."
        ),
        WorkflowStage.COMPLETE: "",
    }
    return prompts[stage]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
