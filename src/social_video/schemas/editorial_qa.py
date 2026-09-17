"""Validated supervising-editor handoff."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from social_video.schemas.base import Artifact


class EditorialQAStatus(str, Enum):
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class EditorialFix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Exact artifact field to change, e.g. ranges[2].end.")
    value: Any
    reason: str = ""


class EditorialQA(Artifact):
    status: EditorialQAStatus
    fixes: list[EditorialFix] = Field(default_factory=list)

    @model_validator(mode="after")
    def _status_matches_fixes(self) -> EditorialQA:
        if self.status is EditorialQAStatus.APPROVED and self.fixes:
            raise ValueError("approved requires fixes=[]")
        if self.status is EditorialQAStatus.CHANGES_REQUESTED and not self.fixes:
            raise ValueError("changes_requested requires at least one fix")
        return self
