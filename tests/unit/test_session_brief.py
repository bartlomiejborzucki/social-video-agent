"""1.5: a session opened in a video project learns which edits are in progress."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from social_video.project_validation import validate_claude_hooks
from social_video.schemas.workflow import RemotionLicenseAttestation, WorkflowStage
from social_video.workflow import create_workflow, load_workflow
from social_video.workflow.brief import edits_in_progress, find_state_files, session_brief
from social_video.workspace.layout import Workspace

REPO = Path(__file__).resolve().parents[2]
# The hook is a bash script for the Linux or WSL engine. On native Windows,
# `bash` is usually the WSL launcher, which fails without a distribution.
HOOK_BASH = shutil.which("bash") is not None and os.name != "nt"
NO_HOOK_BASH = "needs a POSIX bash; on Windows bash.exe is the WSL launcher"


def _edit(project: Path, name: str = "edit") -> Workspace:
    source = project / f"{name}.mp4"
    source.write_bytes(b"fixture")
    workspace = Workspace.at(project / "videos" / name / "edit")
    create_workflow(
        [source],
        workspace,
        project_root=project,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )
    return workspace


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("SOCIAL_VIDEO_HOME", str(home))
    return home


def test_silent_outside_a_video_project(tmp_path: Path, home: Path):
    (tmp_path / "src").mkdir()
    assert session_brief(tmp_path) == []


def test_a_project_config_without_edits_says_how_to_start(tmp_path: Path, home: Path):
    (tmp_path / "social-video.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    lines = session_brief(tmp_path)
    assert "project config: social-video.yaml" in lines[1]
    assert "no edit in progress" in lines[2]


def test_edits_in_progress_are_listed_with_their_stage(tmp_path: Path, home: Path):
    project = tmp_path / "project"
    project.mkdir()
    _edit(project, "first")
    _edit(project, "second")
    lines = session_brief(project)
    assert "2 edits in progress" in lines[1]
    expected = f"{Path('videos/first/edit')}: at stage_1_editorial_plan"  # native separators
    assert any(expected in line for line in lines)
    assert "workflow status" in lines[-1]


def test_a_finished_edit_is_not_listed(tmp_path: Path, home: Path):
    project = tmp_path / "project"
    project.mkdir()
    workspace = _edit(project)
    state = load_workflow(workspace)
    state.current_stage = WorkflowStage.COMPLETE
    workspace.workflow_state.write_text(state.to_json(), encoding="utf-8")
    assert edits_in_progress(project) == []


def test_a_broken_state_is_reported_not_raised(tmp_path: Path, home: Path):
    broken = tmp_path / "old" / "edit"
    broken.mkdir(parents=True)
    (broken / "workflow-state.json").write_text("{", encoding="utf-8")
    [edit] = edits_in_progress(tmp_path)
    assert edit.problem
    assert "cannot be resumed" in session_brief(tmp_path)[2]


def test_the_search_is_bounded(tmp_path: Path):
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "workflow-state.json").write_text("{}", encoding="utf-8")
    skipped = tmp_path / "node_modules" / "edit"
    skipped.mkdir(parents=True)
    (skipped / "workflow-state.json").write_text("{}", encoding="utf-8")
    assert find_state_files(tmp_path) == []


def test_app_home_workspaces_of_this_project_are_found(tmp_path: Path, home: Path):
    project = tmp_path / "project"
    project.mkdir()
    workspace = _edit(project)
    kept = home / "workspaces" / "clip-abc" / "edit"
    shutil.copytree(workspace.root, kept)
    shutil.rmtree(project / "videos")
    [edit] = edits_in_progress(project)
    assert edit.workspace == kept.resolve()


def test_the_plugin_hooks_are_valid():
    assert validate_claude_hooks(REPO / "hooks" / "hooks.json").ok


def test_a_hook_naming_a_missing_script_is_invalid(tmp_path: Path):
    hooks = tmp_path / "hooks" / "hooks.json"
    hooks.parent.mkdir()
    command = 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/nope.sh"'
    start = [{"hooks": [{"type": "command", "command": command}]}]
    hooks.write_text(json.dumps({"hooks": {"SessionStart": start, "OnBoot": []}}), encoding="utf-8")
    errors = validate_claude_hooks(hooks).errors
    assert any("missing file: scripts/nope.sh" in e for e in errors)
    assert any("unknown hook event 'OnBoot'" in e for e in errors)


@pytest.mark.skipif(not HOOK_BASH, reason=NO_HOOK_BASH)
def test_the_hook_script_is_quiet_without_the_cli(tmp_path: Path):
    env = {"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(tmp_path), "HOME": str(tmp_path)}
    script = REPO / "scripts" / "claude" / "session-start.sh"
    quiet = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert (quiet.returncode, quiet.stdout) == (0, "")
    (tmp_path / "social-video.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    hint = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert hint.returncode == 0
    assert "not on PATH" in hint.stdout


@pytest.mark.skipif(not HOOK_BASH, reason=NO_HOOK_BASH)
def test_the_hook_script_prints_the_brief(tmp_path: Path, home: Path):
    cli = shutil.which("social-video-agent")
    if cli is None:
        pytest.skip("social-video-agent is not on PATH")
    project = tmp_path / "project"
    project.mkdir()
    _edit(project)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    script = REPO / "scripts" / "claude" / "session-start.sh"
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert "1 edit in progress" in result.stdout
