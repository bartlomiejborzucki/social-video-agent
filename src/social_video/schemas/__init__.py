"""Versioned, validated artifact schemas.

Every file the agent writes or reads is validated on load. An LLM producing
malformed JSON must fail clearly, naming the offending field, rather than
reaching ffmpeg and dying with a KeyError or a negative ``-t`` value.

Upstream video-use has no schema at all: the EDL contract exists only as a
prose example in SKILL.md, is read by raw dict indexing, and its ``version``
and ``total_duration_s`` fields are never read by any code.
"""

from social_video.schemas.base import (
    SCHEMA_VERSION,
    Artifact,
    load_artifact,
    save_artifact,
    save_artifacts_atomically,
)
from social_video.schemas.brand import (
    BrandProfile,
    CaptionCase,
    CaptionPosition,
    CaptionStyle,
    OutputProfile,
)
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.config import BrandContract, CaptionConfig, ProjectVideoConfig
from social_video.schemas.delivery import DeliveryItem, DeliveryManifest
from social_video.schemas.editorial_qa import EditorialFix, EditorialQA, EditorialQAStatus
from social_video.schemas.edl import (
    EDL,
    CropKeyframe,
    EDLRange,
    Overlay,
    ReframeMode,
    ReframePlan,
    VisualFillStrategy,
)
from social_video.schemas.plan import (
    CandidateScores,
    CandidateSet,
    ClipCandidate,
    EditPlan,
    PlanAction,
    PlanItem,
)
from social_video.schemas.project_context import (
    ContextClaim,
    ContextConfidence,
    ContextSource,
    ContextSources,
    ProjectConfig,
    ProjectContext,
)
from social_video.schemas.qa import QACheck, QAReport, QASeverity, RenderManifest
from social_video.schemas.source import SourceEntry, SourceManifest
from social_video.schemas.transcript import (
    TokenType,
    Transcript,
    TranscriptSegment,
    TranscriptToken,
)
from social_video.schemas.workflow import ModelBudget, WorkflowMode, WorkflowStage, WorkflowState

__all__ = [
    "EDL",
    "SCHEMA_VERSION",
    "Artifact",
    "BrandContract",
    "BrandProfile",
    "CandidateScores",
    "CandidateSet",
    "CaptionCase",
    "CaptionConfig",
    "CaptionCue",
    "CaptionPosition",
    "CaptionStyle",
    "CaptionTrack",
    "CaptionWord",
    "ClipCandidate",
    "ContextClaim",
    "ContextConfidence",
    "ContextSource",
    "ContextSources",
    "CropKeyframe",
    "DeliveryItem",
    "DeliveryManifest",
    "EDLRange",
    "EditPlan",
    "EditorialFix",
    "EditorialQA",
    "EditorialQAStatus",
    "ModelBudget",
    "OutputProfile",
    "Overlay",
    "PlanAction",
    "PlanItem",
    "ProjectConfig",
    "ProjectContext",
    "ProjectVideoConfig",
    "QACheck",
    "QAReport",
    "QASeverity",
    "ReframeMode",
    "ReframePlan",
    "RenderManifest",
    "SourceEntry",
    "SourceManifest",
    "TokenType",
    "Transcript",
    "TranscriptSegment",
    "TranscriptToken",
    "VisualFillStrategy",
    "WorkflowMode",
    "WorkflowStage",
    "WorkflowState",
    "load_artifact",
    "save_artifact",
    "save_artifacts_atomically",
]
