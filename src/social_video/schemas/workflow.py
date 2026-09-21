"""Persistent multi-stage workflow state."""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from social_video.schemas.base import Artifact


class WorkflowMode(str, Enum):
    GUIDED = "guided"
    CONTINUOUS = "continuous"


class ModelBudget(str, Enum):
    ECONOMICAL = "economical"
    BALANCED = "balanced"
    QUALITY = "quality"


class Renderer(str, Enum):
    REMOTION = "remotion"
    FFMPEG = "ffmpeg"


class RemotionLicenseAttestation(str, Enum):
    FREE_LICENSE_ELIGIBLE = "free_license_eligible"
    COMPANY_LICENSE_CONFIRMED = "company_license_confirmed"


class RemotionLicenseSource(str, Enum):
    """Where this edit's declaration came from, so the record stays auditable."""

    CLI_FLAG = "cli_flag"
    PROJECT_DECLARATION = "project_declaration"


class WorkflowStage(str, Enum):
    EDITORIAL_PLAN = "stage_1_editorial_plan"
    EXECUTION = "stage_2_execution"
    EDITORIAL_REVIEW = "stage_3_editorial_review"
    FINALIZATION = "stage_4_finalization"
    DELIVERY = "stage_5_delivery"
    COMPLETE = "complete"


class WorkflowState(Artifact):
    workflow_version: int = 4
    component_versions: dict[str, str] = Field(default_factory=dict)
    target_project_root: str
    workspace: str
    source_media: list[str] = Field(min_length=1)
    current_stage: WorkflowStage = WorkflowStage.EDITORIAL_PLAN
    completed_stages: list[WorkflowStage] = Field(default_factory=list)
    recommended_next_model_tier: str
    recommended_next_model_name: str
    recommended_next_models: dict[str, str] = Field(default_factory=dict)
    recommended_reasoning_effort: str
    recommendation_reason: str
    handoff_required: bool = True
    model_budget: ModelBudget = ModelBudget.BALANCED
    workflow_mode: WorkflowMode = WorkflowMode.GUIDED
    renderer: Renderer = Renderer.FFMPEG
    remotion_license_attestation: RemotionLicenseAttestation | None = None
    remotion_license_checked_at: str | None = None
    #: Absent in workflows created before the project declaration existed;
    #: such a state keeps its own attestation and never has to re-declare.
    remotion_license_source: RemotionLicenseSource | None = None
    project_context_path: str
    edit_plan_path: str
    motion_plan_path: str = ""
    edl_path: str
    preview_path: str
    technical_qa_path: str
    brand_contract_path: str = ""
    brand_qa_path: str = ""
    editorial_qa_path: str
    final_output_path: str
    delivery_manifest_path: str
    created_at: str
    updated_at: str
