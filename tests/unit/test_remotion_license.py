"""The project's Remotion license declaration: storage, precedence, revocation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from social_video.cli import app
from social_video.errors import RemotionLicenseError
from social_video.remotion_license import (
    MAX_DECLARATION_AGE_DAYS,
    attest,
    declaration_path,
    declaration_status,
    refresh,
    resolve_attestation,
    revoke,
)
from social_video.schemas.remotion_license import REMOTION_LICENSE_URL
from social_video.schemas.workflow import (
    RemotionLicenseAttestation,
    RemotionLicenseSource,
    Renderer,
)
from social_video.workflow import create_workflow, load_workflow, workflow_status
from social_video.workspace.layout import Workspace

FREE = RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE
COMPANY = RemotionLicenseAttestation.COMPANY_LICENSE_CONFIRMED


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "input.mp4").write_bytes(b"fixture")
    return project


def _edit(project: Path, name: str = "edit") -> Workspace:
    return Workspace.at(project / name)


def _patch_declaration(project: Path, **changes: object) -> Path:
    path = declaration_path(project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(changes)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- first write -----------------------------------------------------------


def test_first_declaration_records_statement_date_versions_and_terms(tmp_path: Path) -> None:
    project = _project(tmp_path)

    declaration = attest(project, FREE, accept_terms=True, declared_by="Ada")

    assert declaration_path(project) == project / ".social-video/remotion-license.json"
    assert declaration.attestation is FREE
    assert declaration.terms_acknowledged is True
    assert declaration.license_terms_url == REMOTION_LICENSE_URL
    assert declaration.declared_by == "Ada"
    assert declaration.component_versions["cli"]
    assert declaration.component_versions["skill"]
    assert datetime.fromisoformat(declaration.declared_at).tzinfo is not None


def test_first_write_requires_a_conscious_acknowledgement(tmp_path: Path) -> None:
    project = _project(tmp_path)

    with pytest.raises(RemotionLicenseError, match="--accept-terms"):
        attest(project, FREE, accept_terms=False)

    assert not declaration_path(project).exists()


def test_declaration_never_touches_the_branding_config(tmp_path: Path) -> None:
    project = _project(tmp_path)
    config = project / ".social-video/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("brand_name: Acme\n", encoding="utf-8")

    attest(project, FREE, accept_terms=True)

    assert config.read_text(encoding="utf-8") == "brand_name: Acme\n"


@pytest.mark.parametrize("value", ["", "yes", "we_have_2_employees", "free"])
def test_only_the_two_declarations_are_accepted(tmp_path: Path, value: str) -> None:
    with pytest.raises(RemotionLicenseError, match="not a Remotion license declaration"):
        attest(_project(tmp_path), value, accept_terms=True)


def test_existing_declaration_is_not_overwritten_by_accident(tmp_path: Path) -> None:
    project = _project(tmp_path)
    attest(project, FREE, accept_terms=True)

    with pytest.raises(RemotionLicenseError, match="already exists"):
        attest(project, COMPANY, accept_terms=True)

    assert declaration_status(project).declaration is not None
    assert declaration_status(project).declaration.attestation is FREE

    replaced = attest(project, COMPANY, accept_terms=True, replace=True)
    assert replaced.attestation is COMPANY


# --- reuse in a later session ----------------------------------------------


def test_new_session_reuses_the_project_declaration(tmp_path: Path) -> None:
    project = _project(tmp_path)
    attest(project, FREE, accept_terms=True)

    first = create_workflow([project / "input.mp4"], _edit(project, "edit-1"), project_root=project)
    # A different edit in a later session, with no flag and no shared state.
    second = create_workflow(
        [project / "input.mp4"], _edit(project, "edit-2"), project_root=project
    )

    for state in (first, second):
        assert state.renderer is Renderer.REMOTION
        assert state.remotion_license_attestation is FREE
        assert state.remotion_license_source is RemotionLicenseSource.PROJECT_DECLARATION
        assert state.remotion_license_checked_at
    assert workflow_status(second)["remotion_license_source"] == "project_declaration"


def test_cli_flag_overrides_the_stored_declaration(tmp_path: Path) -> None:
    project = _project(tmp_path)
    attest(project, FREE, accept_terms=True)

    state = create_workflow(
        [project / "input.mp4"],
        _edit(project),
        project_root=project,
        remotion_license_attestation=COMPANY,
    )

    assert state.remotion_license_attestation is COMPANY
    assert state.remotion_license_source is RemotionLicenseSource.CLI_FLAG
    # The flag declares for one edit; the project's own statement is unchanged.
    assert declaration_status(project).declaration.attestation is FREE


def test_flag_alone_still_works_without_any_stored_declaration(tmp_path: Path) -> None:
    project = _project(tmp_path)

    state = create_workflow(
        [project / "input.mp4"],
        _edit(project),
        project_root=project,
        remotion_license_attestation=FREE,
    )

    assert state.remotion_license_source is RemotionLicenseSource.CLI_FLAG
    assert not declaration_path(project).exists()


# --- missing, stale and revoked --------------------------------------------


def test_missing_declaration_stops_the_workflow_with_instructions(tmp_path: Path) -> None:
    project = _project(tmp_path)
    workspace = _edit(project)

    with pytest.raises(RemotionLicenseError) as caught:
        create_workflow([project / "input.mp4"], workspace, project_root=project)

    message = str(caught.value)
    assert "remotion-license attest" in message
    assert "free_license_eligible, company_license_confirmed" in message
    assert REMOTION_LICENSE_URL in message
    assert "--renderer ffmpeg" in message
    assert "does not decide eligibility" in message
    assert not workspace.root.exists()


def test_revoked_declaration_stops_the_workflow(tmp_path: Path) -> None:
    project = _project(tmp_path)
    attest(project, FREE, accept_terms=True)

    revoked = revoke(project, reason="company license lapsed")

    assert revoked.revoked_at and revoked.revocation_reason == "company license lapsed"
    status = declaration_status(project)
    assert status.code == "revoked" and not status.usable
    with pytest.raises(RemotionLicenseError, match="was revoked"):
        create_workflow([project / "input.mp4"], _edit(project), project_root=project)


def test_revocation_is_not_undone_by_a_refresh(tmp_path: Path) -> None:
    project = _project(tmp_path)
    attest(project, FREE, accept_terms=True)
    revoke(project)

    with pytest.raises(RemotionLicenseError, match="not reinstated"):
        refresh(project, accept_terms=True)

    reinstated = attest(project, FREE, accept_terms=True, replace=True)
    assert reinstated.revoked_at is None
    assert declaration_status(project).usable


def test_revoking_without_a_declaration_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RemotionLicenseError, match="no readable"):
        revoke(_project(tmp_path))


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"license_terms_url": "https://example.invalid/license"}, "stale_terms"),
        ({"component_versions": {"cli": "0.1.0"}}, "stale_release"),
        ({"declaration_version": 2}, "unsupported_version"),
    ],
)
def test_changed_conditions_require_re_confirmation(
    tmp_path: Path, changes: dict[str, object], code: str
) -> None:
    project = _project(tmp_path)
    attest(project, FREE, accept_terms=True)
    _patch_declaration(project, **changes)

    status = declaration_status(project)

    assert status.code == code and not status.usable
    with pytest.raises(RemotionLicenseError, match=r"cannot be read|needs re-confirming"):
        resolve_attestation(project)


def test_declaration_expires_and_a_refresh_restores_it(tmp_path: Path) -> None:
    project = _project(tmp_path)
    attest(project, FREE, accept_terms=True)
    stale = datetime.now(timezone.utc) - timedelta(days=MAX_DECLARATION_AGE_DAYS + 2)
    _patch_declaration(project, declared_at=stale.isoformat(timespec="seconds"))

    assert declaration_status(project).code == "expired"
    with pytest.raises(RemotionLicenseError, match="remotion-license refresh"):
        resolve_attestation(project)

    refreshed = refresh(project, accept_terms=True)

    assert refreshed.attestation is FREE
    assert declaration_status(project).usable
    assert resolve_attestation(project) == (FREE, RemotionLicenseSource.PROJECT_DECLARATION)


def test_refresh_also_requires_the_acknowledgement(tmp_path: Path) -> None:
    project = _project(tmp_path)
    attest(project, FREE, accept_terms=True)

    with pytest.raises(RemotionLicenseError, match="--accept-terms"):
        refresh(project, accept_terms=False)


def test_unreadable_declaration_is_reported_not_ignored(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = declaration_path(project)
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")

    status = declaration_status(project)

    assert status.code == "unreadable" and status.present
    with pytest.raises(RemotionLicenseError, match="cannot be read"):
        resolve_attestation(project)


def test_declaration_without_acknowledgement_on_disk_is_rejected(tmp_path: Path) -> None:
    project = _project(tmp_path)
    attest(project, FREE, accept_terms=True)
    _patch_declaration(project, terms_acknowledged=False)

    assert declaration_status(project).code == "unreadable"


def test_ffmpeg_renderer_needs_no_declaration(tmp_path: Path) -> None:
    project = _project(tmp_path)

    state = create_workflow(
        [project / "input.mp4"], _edit(project), project_root=project, renderer=Renderer.FFMPEG
    )

    assert state.remotion_license_attestation is None
    assert state.remotion_license_source is None


# --- older workspaces -------------------------------------------------------


def test_workflow_state_without_a_source_field_resumes_unchanged(tmp_path: Path) -> None:
    """A workspace created before the project declaration keeps its own answer."""
    project = _project(tmp_path)
    workspace = _edit(project)
    create_workflow(
        [project / "input.mp4"],
        workspace,
        project_root=project,
        remotion_license_attestation=FREE,
    )
    payload = json.loads(workspace.workflow_state.read_text(encoding="utf-8"))
    payload.pop("remotion_license_source")
    workspace.workflow_state.write_text(json.dumps(payload), encoding="utf-8")
    # No declaration exists for the project, so resuming must not consult one.
    assert not declaration_path(project).exists()

    state = load_workflow(workspace)

    assert state.remotion_license_attestation is FREE
    assert state.remotion_license_source is None
    assert workflow_status(state)["remotion_license_attestation"] == "free_license_eligible"


# --- CLI --------------------------------------------------------------------


def test_cli_attest_status_and_revoke(tmp_path: Path) -> None:
    project = _project(tmp_path)
    runner = CliRunner()

    absent = runner.invoke(app, ["remotion-license", "status", "--project-root", str(project)])
    assert absent.exit_code == 0
    assert "no declaration recorded" in absent.stdout

    refused = runner.invoke(
        app, ["remotion-license", "attest", "free_license_eligible", "--project-root", str(project)]
    )
    assert refused.exit_code == 1
    assert not declaration_path(project).exists()

    recorded = runner.invoke(
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
    assert recorded.exit_code == 0
    assert declaration_path(project).is_file()

    status = runner.invoke(
        app, ["remotion-license", "status", "--project-root", str(project), "--json"]
    )
    payload = json.loads(status.stdout)
    assert payload["usable"] is True
    assert payload["attestation"] == "free_license_eligible"
    assert payload["license_terms_url"] == REMOTION_LICENSE_URL

    revoked = runner.invoke(
        app, ["remotion-license", "revoke", "--project-root", str(project), "--reason", "audit"]
    )
    assert revoked.exit_code == 0
    after = runner.invoke(
        app, ["remotion-license", "status", "--project-root", str(project), "--json"]
    )
    assert json.loads(after.stdout)["usable"] is False
