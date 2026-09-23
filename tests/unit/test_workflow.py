from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from social_video.errors import RemotionLicenseError, ValidationError
from social_video.pipeline import stage_plan
from social_video.profiles import load_profile
from social_video.schemas.base import save_artifact
from social_video.schemas.editorial_qa import EditorialQA, EditorialQAStatus
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionPlan
from social_video.schemas.plan import EditPlan
from social_video.schemas.qa import QACheck, QAReport, QASeverity
from social_video.schemas.transcript import Transcript
from social_video.schemas.workflow import (
    ModelBudget,
    RemotionLicenseAttestation,
    Renderer,
    WorkflowMode,
    WorkflowStage,
)
from social_video.workflow import advance_workflow, create_workflow, load_workflow, workflow_status
from social_video.workspace.layout import Workspace


def _setup(tmp_path: Path, **kwargs):
    project = tmp_path / "project"
    project.mkdir()
    (project / "docs").mkdir()
    (project / "docs/video-guidelines.md").write_text(
        "Use calm educational edits and restrained captions.", encoding="utf-8"
    )
    source = project / "input.mp4"
    source.write_bytes(b"fixture")
    workspace = Workspace.at(tmp_path / "workspace/edit")
    kwargs.setdefault(
        "remotion_license_attestation",
        RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )
    state = create_workflow([source], workspace, project_root=project, **kwargs)
    return project, source, workspace, state


def _write_stage_1(workspace: Workspace) -> None:
    save_artifact(
        EditPlan(
            goal="Create a Reel",
            strategy="Calm standalone explanation.",
            style_sources=["docs/video-guidelines.md"],
        ),
        workspace.edit_plan,
    )


def _write_stage_2(workspace: Workspace) -> None:
    save_artifact(
        EDL(ranges=[EDLRange(source="source-1", start=0, end=1)], output_fps="30/1"),
        workspace.edl,
    )
    workspace.previews.mkdir(parents=True, exist_ok=True)
    (workspace.previews / "preview.mp4").write_bytes(b"preview")
    save_artifact(QAReport(output="preview.mp4"), workspace.technical_qa)
    save_artifact(
        MotionPlan(rationale="A restrained branded layer supports the approved story."),
        workspace.motion_plan,
    )


def _write_stage_3(workspace: Workspace) -> None:
    save_artifact(EditorialQA(status=EditorialQAStatus.APPROVED, fixes=[]), workspace.editorial_qa)


def test_guided_handoffs_persist_and_stage_1_does_not_render(tmp_path: Path) -> None:
    _, _, workspace, state = _setup(tmp_path)

    assert state.current_stage is WorkflowStage.EDITORIAL_PLAN
    assert state.recommended_next_model_tier == "editorial_strong"
    assert state.recommended_next_model_name == "Astra"
    assert state.recommended_next_models == {
        "openai": "Astra",
        "claude": "Claude Opus 5",
    }
    assert state.renderer is Renderer.REMOTION
    assert state.remotion_license_attestation is RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE
    assert not (workspace.final / "final.mp4").exists()

    _write_stage_1(workspace)
    stage_2 = advance_workflow(workspace, WorkflowStage.EDITORIAL_PLAN)
    assert stage_2.current_stage is WorkflowStage.EXECUTION
    assert stage_2.recommended_next_model_name == "Sol"
    assert stage_2.recommended_next_models["claude"] == "Claude Sonnet 5"
    assert load_workflow(workspace) == stage_2

    _write_stage_2(workspace)
    stage_3 = advance_workflow(workspace, WorkflowStage.EXECUTION)
    assert stage_3.current_stage is WorkflowStage.EDITORIAL_REVIEW
    assert stage_3.recommended_next_model_name == "Astra"
    assert stage_3.recommended_next_models["claude"] == "Claude Opus 5"

    _write_stage_3(workspace)
    stage_4 = advance_workflow(workspace, WorkflowStage.EDITORIAL_REVIEW)
    assert stage_4.current_stage is WorkflowStage.FINALIZATION
    assert stage_4.recommended_next_model_name == "Sol"
    assert stage_4.recommended_next_models == {
        "openai": "Sol",
        "claude": "Claude Sonnet 5",
    }
    assert workflow_status(stage_4, language="pl")["next_models"] == {
        "openai": "Sol",
        "claude": "Claude Sonnet 5",
    }


def test_stage_plan_records_discovered_style_sources(tmp_path: Path) -> None:
    _, _, workspace, _ = _setup(tmp_path)
    transcript = Transcript(
        source_id="input",
        source_fingerprint="fixture",
        duration=1,
        provider="fixture",
    )

    plan = stage_plan(
        transcript,
        workspace,
        load_profile("talking-head"),
        goal="Project-aware Reel",
    )

    assert plan.style_sources == ["docs/video-guidelines.md"]


def test_stage_5_never_changes_edl(tmp_path: Path) -> None:
    _, _, workspace, _ = _setup(tmp_path)
    _write_stage_1(workspace)
    advance_workflow(workspace, WorkflowStage.EDITORIAL_PLAN)
    _write_stage_2(workspace)
    advance_workflow(workspace, WorkflowStage.EXECUTION)
    _write_stage_3(workspace)
    advance_workflow(workspace, WorkflowStage.EDITORIAL_REVIEW)
    (workspace.final / "final.mp4").write_bytes(b"final")
    save_artifact(QAReport(output="final.mp4"), workspace.technical_qa)
    stage_5 = advance_workflow(workspace, WorkflowStage.FINALIZATION)
    assert stage_5.current_stage is WorkflowStage.DELIVERY
    assert stage_5.recommended_next_models == {
        "openai": "Luna",
        "claude": "Claude Haiku 4.5",
    }
    assert workflow_status(stage_5, language="pl")["next_models"] == {
        "openai": "Luna",
        "claude": "Claude Haiku 4.5",
    }
    before = hashlib.sha256(workspace.edl.read_bytes()).hexdigest()
    workspace.delivery_manifest.write_text(
        json.dumps({"files": ["final.mp4", "captions.srt"]}), encoding="utf-8"
    )

    complete = advance_workflow(workspace, WorkflowStage.DELIVERY)

    assert complete.current_stage is WorkflowStage.COMPLETE
    assert hashlib.sha256(workspace.edl.read_bytes()).hexdigest() == before


def test_continuous_mode_keeps_artifacts_but_requires_no_model_switch(tmp_path: Path) -> None:
    _, _, _, state = _setup(tmp_path, workflow_mode=WorkflowMode.CONTINUOUS)

    status = workflow_status(state, language="pl")

    assert status["language"] == "pl"
    assert status["handoff_required"] is False
    assert status["next_model"] == "current model"
    assert status["next_models"] == {
        "openai": "Astra",
        "claude": "Claude Opus 5",
    }
    assert status["next_prompt"] == "Kontynuuj social-video-agent z Etapem 1."
    assert status["reason"].startswith("Zrozumienie projektu")


def test_economical_routing_uses_balanced_then_fast_tiers(tmp_path: Path) -> None:
    _, _, workspace, state = _setup(tmp_path, model_budget=ModelBudget.ECONOMICAL)
    assert state.recommended_next_model_name == "Sol"
    _write_stage_1(workspace)

    state = advance_workflow(workspace, WorkflowStage.EDITORIAL_PLAN)

    assert state.recommended_next_model_tier == "mechanical_fast"
    assert state.recommended_next_model_name == "Luna"


def test_explicit_project_config_can_set_budget_and_mode(tmp_path: Path) -> None:
    project = tmp_path / "configured"
    project.mkdir()
    (project / "social-video.yaml").write_text(
        "model_budget: economical\nworkflow_mode: continuous\n", encoding="utf-8"
    )
    source = project / "input.mp4"
    source.write_bytes(b"fixture")
    workspace = Workspace.at(tmp_path / "configured-workspace/edit")

    state = create_workflow(
        [source],
        workspace,
        project_root=project,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )

    assert state.model_budget is ModelBudget.ECONOMICAL
    assert state.workflow_mode is WorkflowMode.CONTINUOUS
    assert state.recommended_next_model_name == "current model"


def test_status_reports_required_and_missing_artifacts(tmp_path: Path) -> None:
    _, _, _, state = _setup(tmp_path)

    status = workflow_status(state)

    assert state.project_context_path in status["required_artifacts"]
    assert state.edit_plan_path in status["missing_artifacts"]
    assert state.project_context_path not in status["missing_artifacts"]


def test_stage_0_blocks_remotion_before_creating_workspace_without_attestation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "input.mp4"
    source.write_bytes(b"fixture")
    workspace = Workspace.at(tmp_path / "blocked/edit")

    with pytest.raises(RemotionLicenseError, match="no recorded Remotion license"):
        create_workflow([source], workspace, project_root=project)

    assert not workspace.root.exists()


def test_explicit_ffmpeg_renderer_does_not_require_remotion_license(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "input.mp4"
    source.write_bytes(b"fixture")

    state = create_workflow(
        [source],
        Workspace.at(tmp_path / "ffmpeg/edit"),
        project_root=project,
        renderer=Renderer.FFMPEG,
    )

    assert state.renderer is Renderer.FFMPEG
    assert state.remotion_license_attestation is None


def test_version_1_state_gets_provider_recommendations_on_resume(tmp_path: Path) -> None:
    _, _, workspace, _ = _setup(tmp_path)
    payload = json.loads(workspace.workflow_state.read_text(encoding="utf-8"))
    payload["workflow_version"] = 1
    payload.pop("recommended_next_models")
    workspace.workflow_state.write_text(json.dumps(payload), encoding="utf-8")

    status = workflow_status(load_workflow(workspace), language="pl")

    assert status["next_models"] == {
        "openai": "Astra",
        "claude": "Claude Opus 5",
    }


def test_failed_technical_qa_blocks_stage_handoff(tmp_path: Path) -> None:
    _, _, workspace, _ = _setup(tmp_path)
    _write_stage_1(workspace)
    advance_workflow(workspace, WorkflowStage.EDITORIAL_PLAN)
    _write_stage_2(workspace)
    save_artifact(
        QAReport(
            output="preview.mp4",
            checks=[
                QACheck(
                    name="decode",
                    severity=QASeverity.ERROR,
                    passed=False,
                    message="decode failed",
                )
            ],
        ),
        workspace.technical_qa,
    )

    with pytest.raises(ValidationError, match="technical QA failed"):
        advance_workflow(workspace, WorkflowStage.EXECUTION)


def test_a_legacy_ffmpeg_workflow_switches_to_remotion_through_the_licence_gate(
    tmp_path: Path,
) -> None:
    from social_video.workflow import set_renderer

    _, _, workspace, _ = _setup(
        tmp_path, renderer=Renderer.FFMPEG, remotion_license_attestation=None
    )
    _write_stage_1(workspace)
    advance_workflow(workspace, WorkflowStage.EDITORIAL_PLAN)
    _write_stage_2(workspace)
    advance_workflow(workspace, WorkflowStage.EXECUTION)

    with pytest.raises(RemotionLicenseError):
        set_renderer(workspace, Renderer.REMOTION)
    assert load_workflow(workspace).renderer is Renderer.FFMPEG

    state = set_renderer(
        workspace,
        Renderer.REMOTION,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )

    assert state.renderer is Renderer.REMOTION
    assert state.remotion_license_attestation is RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE
    # The preview came from the other renderer, so Stage 2 is open again.
    assert state.current_stage is WorkflowStage.EXECUTION
    assert state.completed_stages == [WorkflowStage.EDITORIAL_PLAN]
    assert load_workflow(workspace).renderer is Renderer.REMOTION
