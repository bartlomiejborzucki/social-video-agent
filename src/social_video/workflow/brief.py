"""What an agent starting a session in a project should know, in a few lines.

A staged edit is resumed from files, but only if the agent knows the files are
there. At session start this finds the edits in progress for the directory
the agent opened -- next to the project, and in the app-home workspaces used
for Windows-drive sources -- and says which stage each is at and how to resume.

It is quiet by design. Outside a video project it prints nothing, so a plugin
installed for every session costs nothing where it does not apply. It reads
files only and never fails: a broken state is reported, not raised.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from social_video import __version__
from social_video.errors import SocialVideoError
from social_video.paths import app_home
from social_video.project_config import find_project_config
from social_video.schemas.workflow import WorkflowStage
from social_video.workspace.layout import Workspace

STATE_NAME = "workflow-state.json"
#: How deep below the opened directory to look for edit workspaces.
MAX_DEPTH = 3
#: Directories never worth descending into.
SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "cache", "renders", "final"}
#: Directories visited before giving up, so a huge tree cannot stall a session.
MAX_VISITS = 400
#: Edits listed; the rest are counted.
MAX_LISTED = 5


@dataclass(frozen=True)
class EditInProgress:
    workspace: Path
    stage: str
    updated_at: str
    missing: tuple[str, ...] = ()
    problem: str | None = None


def find_state_files(root: Path) -> list[Path]:
    """``workflow-state.json`` files at most ``MAX_DEPTH`` directories below ``root``."""
    found: list[Path] = []
    queue: list[tuple[Path, int]] = [(root, 0)]
    visits = 0
    while queue and visits < MAX_VISITS:
        directory, depth = queue.pop(0)
        visits += 1
        candidate = directory / STATE_NAME
        if candidate.is_file():
            found.append(candidate)
        if depth >= MAX_DEPTH:
            continue
        try:
            children = sorted(p for p in directory.iterdir() if p.is_dir())
        except OSError:
            continue
        for child in children:
            if child.name in SKIP or child.name.startswith(".") or child.is_symlink():
                continue
            queue.append((child, depth + 1))
    return found


def _app_home_states(root: Path) -> list[Path]:
    """Workspaces kept in the app home whose target project is ``root`` or inside it."""
    base = app_home() / "workspaces"
    if not base.is_dir():
        return []
    states: list[Path] = []
    for candidate in sorted(base.glob(f"*/*/{STATE_NAME}"))[:MAX_VISITS]:
        target = _target_root(candidate)
        if target is not None and (target == root or root in target.parents):
            states.append(candidate)
    return states


def _target_root(state_file: Path) -> Path | None:
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return Path(data["target_project_root"]).resolve()
    except (OSError, ValueError, KeyError, TypeError):
        return None


def edits_in_progress(root: Path) -> list[EditInProgress]:
    from social_video.workflow import load_workflow, workflow_status

    root = root.resolve()
    seen: set[Path] = set()
    edits: list[EditInProgress] = []
    for state_file in [*find_state_files(root), *_app_home_states(root)]:
        folder = state_file.parent.resolve()
        if folder in seen:
            continue
        seen.add(folder)
        workspace = Workspace(root=folder)
        try:
            state = load_workflow(workspace)
        except (SocialVideoError, OSError, ValueError) as exc:
            edits.append(EditInProgress(folder, "unreadable", "", problem=str(exc)))
            continue
        if state.current_stage is WorkflowStage.COMPLETE:
            continue
        status = workflow_status(state)
        edits.append(
            EditInProgress(
                workspace=folder,
                stage=state.current_stage.value,
                updated_at=state.updated_at,
                missing=tuple(status["missing_artifacts"]),
            )
        )
    return sorted(edits, key=lambda e: e.updated_at, reverse=True)


def session_brief(root: Path) -> list[str]:
    """Lines for the agent's context, or none when this is not a video project."""
    root = root.resolve()
    edits = edits_in_progress(root)
    config = find_project_config(root)
    if not edits and config is None:
        return []
    lines = [f"social-video-agent {__version__} (skill: social-video-agent)"]
    if config is not None:
        lines.append(f"- project config: {_show(config, root)}")
    if not edits:
        lines.append("- no edit in progress; start one with the social-video-agent skill")
        return lines
    noun = "edit" if len(edits) == 1 else "edits"
    lines.append(f"- {len(edits)} {noun} in progress, newest first:")
    for edit in edits[:MAX_LISTED]:
        where = _show(edit.workspace, root)
        if edit.problem:
            lines.append(f"  - {where}: cannot be resumed as is: {edit.problem}")
            continue
        line = f"  - {where}: at {edit.stage}"
        if edit.missing:
            line += f", missing {', '.join(Path(m).name for m in edit.missing[:3])}"
        lines.append(line)
    if len(edits) > MAX_LISTED:
        lines.append(f"  - and {len(edits) - MAX_LISTED} more")
    lines.append(
        "- resume from files, not chat history: `social-video-agent workflow status <workspace>`"
    )
    return lines


def _show(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)) or "."
    except ValueError:
        return str(path)
