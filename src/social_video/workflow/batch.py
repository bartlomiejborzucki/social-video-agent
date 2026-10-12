"""Several recordings, one brand: a parent workspace over one edit per recording.

Each recording gets an ordinary workspace of its own, with its own stages,
artifacts and handoffs; the parent only lists them. Every child compiles the
same project config, so they share one brand contract, and status reports
when they no longer do -- a config edited halfway through a batch would
otherwise ship two looks under one name.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import Field

from social_video.errors import ValidationError
from social_video.fsutil import utc_timestamp
from social_video.schemas.base import Artifact, load_artifact, save_artifact
from social_video.schemas.config import BrandContract
from social_video.schemas.workflow import WorkflowStage
from social_video.workflow.service import create_workflow, load_workflow, workflow_status
from social_video.workspace.layout import Workspace

VIDEO = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v"})


class BatchItem(Artifact):
    source: str
    workspace: str


class BatchState(Artifact):
    """The recordings of one batch and where each one is edited."""

    root: str
    project_root: str
    created_at: str
    items: list[BatchItem] = Field(min_length=1)


def batch_file(parent: Workspace) -> Path:
    return parent.root / "batch.json"


def is_batch(parent: Workspace) -> bool:
    return batch_file(parent).is_file()


def recordings(directory: Path) -> list[Path]:
    """The video files directly in ``directory``, in name order."""
    if not directory.is_dir():
        raise ValidationError(f"no folder of recordings at {directory}")
    # Sorted by the name as written: Windows compares paths without case, and
    # the order of a batch must not depend on the machine.
    found = sorted(
        (p for p in directory.iterdir() if p.is_file() and p.suffix.casefold() in VIDEO),
        key=lambda p: p.name,
    )
    if not found:
        raise ValidationError(f"no recordings ({', '.join(sorted(VIDEO))}) in {directory}")
    return found


def create_batch(
    directory: Path,
    parent: Workspace,
    *,
    project_root: Path | None = None,
    **workflow: Any,
) -> BatchState:
    """One child workspace per recording, each through the ordinary Stage 0."""
    if is_batch(parent):
        raise ValidationError(f"{parent.root} already holds a batch; check `workflow status`")
    sources = recordings(directory)
    parent.root.mkdir(parents=True, exist_ok=True)
    items: list[BatchItem] = []
    used: set[str] = set()
    target_root = ""
    for source in sources:
        base = name = _slug(source.stem)
        number = 2
        while name in used:
            name = f"{base}-{number}"
            number += 1
        used.add(name)
        child = Workspace.at(parent.root / name)
        state = create_workflow([source], child, project_root=project_root, **workflow)
        target_root = state.target_project_root
        items.append(BatchItem(source=str(source.resolve()), workspace=str(child.root)))
    batch = BatchState(
        root=str(parent.root), project_root=target_root, created_at=utc_timestamp(), items=items
    )
    save_artifact(batch, batch_file(parent))
    return batch


def batch_status(parent: Workspace, *, language: str = "en") -> dict[str, Any]:
    """Where every recording of the batch stands, and which to work on next."""
    batch = load_artifact(BatchState, batch_file(parent))
    children = []
    contracts: set[str] = set()
    for item in batch.items:
        ws = Workspace.at(item.workspace)
        state = load_workflow(ws)
        status = workflow_status(state, language=language)
        if ws.brand_contract.is_file():
            contracts.add(load_artifact(BrandContract, ws.brand_contract).project_config_sha256)
        children.append(
            {
                "source": item.source,
                "workspace": item.workspace,
                "current_stage": status["current_stage"],
                "missing_artifacts": status["missing_artifacts"],
                "pending_motion_films": status["pending_motion_films"],
                "next_prompt": status["next_prompt"],
            }
        )
    complete = WorkflowStage.COMPLETE.value
    stages: dict[str, int] = {}
    for child in children:
        stages[child["current_stage"]] = stages.get(child["current_stage"], 0) + 1
    upcoming = next((c for c in children if c["current_stage"] != complete), None)
    return {
        "batch": batch.root,
        "project_root": batch.project_root,
        "recordings": len(children),
        "complete": stages.get(complete, 0),
        "by_stage": stages,
        "shared_brand_contract": len(contracts) <= 1,
        "brand_contracts": sorted(contracts),
        "next": upcoming["workspace"] if upcoming else None,
        "children": children,
    }


def _slug(stem: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.").casefold()
    return slug[:60] or "recording"
