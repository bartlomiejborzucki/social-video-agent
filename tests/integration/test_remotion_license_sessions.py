"""The declaration survives across sessions, driven through the real CLI.

These go through `typer` and real media so the gate is exercised the way a user
meets it: one declaration, then several edits and several sessions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from social_video.cli import app
from tests.conftest import make_video, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

runner = CliRunner()


def _project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "customer-project"
    project.mkdir()
    source = make_video(project / "talk.mp4", width=640, height=360, duration=1.0)
    return project, source


def _init(project: Path, source: Path, workspace: Path, *args: str):
    return runner.invoke(
        app,
        [
            "workflow",
            "init",
            str(source),
            "--project-root",
            str(project),
            "--workspace",
            str(workspace),
            "--json",
            *args,
        ],
    )


def _state(workspace: Path) -> dict:
    return json.loads((workspace / "workflow-state.json").read_text(encoding="utf-8"))


def test_one_declaration_serves_later_edits_and_sessions(tmp_path: Path) -> None:
    project, source = _project(tmp_path)

    # Session 1: no declaration yet, so the workflow refuses to start.
    blocked = _init(project, source, tmp_path / "edit-0")
    assert blocked.exit_code == 1
    assert "remotion-license" in blocked.stderr
    assert "renderer ffmpeg" in blocked.stderr
    assert not (tmp_path / "edit-0").exists()

    attested = runner.invoke(
        app,
        [
            "remotion-license",
            "attest",
            "free_license_eligible",
            "--project-root",
            str(project),
            "--accept-terms",
            "--declared-by",
            "Ada",
        ],
    )
    assert attested.exit_code == 0

    first = _init(project, source, tmp_path / "edit-1")
    assert first.exit_code == 0, first.stdout
    assert _state(tmp_path / "edit-1")["remotion_license_source"] == "project_declaration"

    # Session 2: a new edit, a new process, no flag and no shared state.
    second = _init(project, source, tmp_path / "edit-2")
    assert second.exit_code == 0, second.stdout
    state = _state(tmp_path / "edit-2")
    assert state["remotion_license_attestation"] == "free_license_eligible"
    assert state["remotion_license_source"] == "project_declaration"

    # An explicit flag still wins for that one edit only.
    overridden = _init(
        project, source, tmp_path / "edit-3", "--remotion-license", "company_license_confirmed"
    )
    assert overridden.exit_code == 0, overridden.stdout
    third = _state(tmp_path / "edit-3")
    assert third["remotion_license_attestation"] == "company_license_confirmed"
    assert third["remotion_license_source"] == "cli_flag"
    stored = runner.invoke(
        app, ["remotion-license", "status", "--project-root", str(project), "--json"]
    )
    assert json.loads(stored.stdout)["attestation"] == "free_license_eligible"

    # Revoking stops new edits and says exactly what to do.
    revoked = runner.invoke(
        app,
        ["remotion-license", "revoke", "--project-root", str(project), "--reason", "yearly review"],
    )
    assert revoked.exit_code == 0
    stopped = _init(project, source, tmp_path / "edit-4")
    assert stopped.exit_code == 1
    assert "revoked" in stopped.stderr and "yearly review" in stopped.stderr
    assert not (tmp_path / "edit-4").exists()

    # Opting out of Remotion never needed a declaration in the first place.
    ffmpeg_route = _init(project, source, tmp_path / "edit-5", "--renderer", "ffmpeg")
    assert ffmpeg_route.exit_code == 0, ffmpeg_route.stdout
    # Nothing was declared for that edit, so nothing is recorded for it.
    assert "remotion_license_attestation" not in _state(tmp_path / "edit-5")
    assert "remotion_license_source" not in _state(tmp_path / "edit-5")


def test_render_also_falls_back_to_the_project_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from social_video.schemas.base import save_artifact
    from social_video.schemas.edl import EDL, EDLRange
    from social_video.sources import build_manifest
    from social_video.workspace.layout import Workspace

    project, source = _project(tmp_path)
    workspace = Workspace.at(project / "edit")
    workspace.ensure()
    manifest = build_manifest([source])
    save_artifact(manifest, workspace.source_manifest)
    save_artifact(
        EDL(
            ranges=[EDLRange(source=manifest.sources[0].id, start=0, end=0.5)],
            output_fps="30/1",
        ),
        workspace.edl,
    )
    # `render` resolves the project root from the working directory when the
    # workspace has no workflow-state.json of its own.
    monkeypatch.chdir(project)

    blocked = runner.invoke(app, ["render", str(workspace.root), "--quality", "draft"])
    assert blocked.exit_code == 1
    assert "remotion-license" in blocked.stderr

    runner.invoke(
        app,
        [
            "remotion-license",
            "attest",
            "free_license_eligible",
            "--project-root",
            str(project),
            "--accept-terms",
        ],
    )
    # The declaration is now found, so the refusal moves on to the next
    # requirement instead of the license.
    accepted = runner.invoke(app, ["render", str(workspace.root), "--quality", "draft"])
    assert accepted.exit_code == 1
    assert "remotion-license" not in accepted.stderr
    assert "motion-plan" in accepted.stderr or "MotionPlan" in accepted.stderr
