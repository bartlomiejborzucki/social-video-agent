"""Record, read and revoke one project's Remotion license declaration.

``workflow init --remotion-license`` declares for a single edit: the statement
lands in that workspace's ``workflow-state.json`` and dies with it, so the next
recording in the same project asks again. A licensing position belongs to the
project, not to one cut of one video, so it is stored once in
``.social-video/remotion-license.json`` and reused.

It is kept out of ``.social-video/config.yaml`` deliberately. That file is
branding: it is edited to change how videos look, it is reasonable to copy
between projects, and it is often written by an agent. A license declaration is
none of those things.

Resolution order, most specific first:

1. an explicit ``--remotion-license`` flag, which overrides whatever is stored;
2. a usable stored declaration for the project;
3. nothing -- the workflow stops with the full instruction.

A stored declaration stops being usable when it was revoked, when it was made
against different terms than this build points at, when it was made under an
older release line, or when it is older than a year. Each of those asks the
user again rather than assuming the old answer still holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from social_video.compatibility import component_versions
from social_video.errors import RemotionLicenseError, ValidationError
from social_video.fsutil import utc_timestamp
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.remotion_license import (
    REMOTION_LICENSE_URL,
    RemotionLicenseDeclaration,
)
from social_video.schemas.workflow import RemotionLicenseAttestation, RemotionLicenseSource

#: Project-relative location. Beside the config, never inside it.
DECLARATION_RELATIVE_PATH = Path(".social-video/remotion-license.json")
#: A declaration is a statement about today's terms, so it is not kept forever.
MAX_DECLARATION_AGE_DAYS = 365

_CHOICES = ", ".join(item.value for item in RemotionLicenseAttestation)


@dataclass(frozen=True)
class DeclarationStatus:
    """What is on disk and whether a workflow may rely on it."""

    path: Path
    code: str
    detail: str
    declaration: RemotionLicenseDeclaration | None = None

    @property
    def usable(self) -> bool:
        return self.code == "valid"

    @property
    def present(self) -> bool:
        return self.declaration is not None or self.code == "unreadable"


def declaration_path(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / DECLARATION_RELATIVE_PATH


def declaration_status(project_root: str | Path) -> DeclarationStatus:
    """Report the stored declaration without raising; `status` has to show it."""
    path = declaration_path(project_root)
    if not path.is_file():
        return DeclarationStatus(path, "absent", "no declaration recorded for this project")
    try:
        declaration = load_artifact(RemotionLicenseDeclaration, path)
    except ValidationError as exc:
        return DeclarationStatus(path, "unreadable", str(exc))
    return _evaluate(path, declaration)


def _evaluate(path: Path, declaration: RemotionLicenseDeclaration) -> DeclarationStatus:
    if declaration.revoked:
        reason = declaration.revocation_reason or "no reason recorded"
        return DeclarationStatus(
            path,
            "revoked",
            f"revoked on {declaration.revoked_at} ({reason})",
            declaration,
        )
    if declaration.declaration_version != 1:
        return DeclarationStatus(
            path,
            "unsupported_version",
            f"declaration_version {declaration.declaration_version} is not readable by this build",
            declaration,
        )
    if declaration.license_terms_url != REMOTION_LICENSE_URL:
        return DeclarationStatus(
            path,
            "stale_terms",
            f"declared against {declaration.license_terms_url}, but this build points at "
            f"{REMOTION_LICENSE_URL}",
            declaration,
        )
    current = component_versions().get("cli", "")
    declared = declaration.component_versions.get("cli", "")
    if _release_line(declared) != _release_line(current):
        return DeclarationStatus(
            path,
            "stale_release",
            f"declared under {declared or 'an unrecorded version'}, and this is {current}",
            declaration,
        )
    age = _age_days(declaration.declared_at)
    if age is None:
        return DeclarationStatus(
            path,
            "unreadable",
            f"declared_at is not a timestamp: {declaration.declared_at!r}",
            declaration,
        )
    if age > MAX_DECLARATION_AGE_DAYS:
        return DeclarationStatus(
            path,
            "expired",
            f"declared {age} days ago; declarations are re-confirmed after "
            f"{MAX_DECLARATION_AGE_DAYS} days",
            declaration,
        )
    return DeclarationStatus(
        path,
        "valid",
        f"{declaration.attestation.value} declared on {declaration.declared_at}",
        declaration,
    )


def read_declaration(project_root: str | Path) -> RemotionLicenseDeclaration | None:
    """Return the stored declaration only when a workflow may rely on it."""
    status = declaration_status(project_root)
    return status.declaration if status.usable else None


def attest(
    project_root: str | Path,
    attestation: RemotionLicenseAttestation | str,
    *,
    accept_terms: bool,
    declared_by: str | None = None,
    note: str | None = None,
    replace: bool = False,
) -> RemotionLicenseDeclaration:
    """Write the project's declaration. Refuses to invent the acknowledgement."""
    value = _parse(attestation)
    if not accept_terms:
        raise RemotionLicenseError(
            "recording a Remotion license declaration requires an explicit "
            "acknowledgement of the terms. Read "
            f"{REMOTION_LICENSE_URL} and re-run with --accept-terms.\n"
            "This is the user's statement to make: an assistant must ask and use the "
            "answer given, not supply the acknowledgement on the user's behalf. This "
            "tool does not assess eligibility from company size, revenue, or any other "
            "data, and it never will."
        )
    path = declaration_path(project_root)
    existing = declaration_status(project_root)
    if existing.present and not replace:
        raise RemotionLicenseError(
            f"a Remotion license declaration already exists: {path} "
            f"({existing.detail}). Re-run with --replace to record a new statement, or "
            "use `remotion-license revoke` first."
        )
    declaration = RemotionLicenseDeclaration(
        attestation=value,
        terms_acknowledged=True,
        license_terms_url=REMOTION_LICENSE_URL,
        declared_at=utc_timestamp(),
        declared_by=declared_by,
        note=note,
        component_versions=component_versions(),
    )
    save_artifact(declaration, path)
    return declaration


def refresh(project_root: str | Path, *, accept_terms: bool) -> RemotionLicenseDeclaration:
    """Re-confirm the same declaration against today's terms and build."""
    status = declaration_status(project_root)
    if status.declaration is None:
        replace = " --replace" if status.present else ""
        raise RemotionLicenseError(
            f"nothing to refresh: {status.path} holds no readable declaration "
            f"({status.detail}). Make the statement with `remotion-license attest "
            f"DECLARATION --accept-terms{replace}` instead."
        )
    if status.declaration.revoked:
        raise RemotionLicenseError(
            "this project's declaration was revoked and is not reinstated by a refresh. "
            "Make the statement again with `remotion-license attest DECLARATION "
            "--accept-terms --replace`."
        )
    return attest(
        project_root,
        status.declaration.attestation,
        accept_terms=accept_terms,
        declared_by=status.declaration.declared_by,
        note=status.declaration.note,
        replace=True,
    )


def revoke(project_root: str | Path, *, reason: str | None = None) -> RemotionLicenseDeclaration:
    """Withdraw the declaration, keeping the record of what was withdrawn."""
    status = declaration_status(project_root)
    if status.declaration is None:
        raise RemotionLicenseError(
            f"no readable Remotion license declaration to revoke: {status.path} ({status.detail})"
        )
    if status.declaration.revoked:
        raise RemotionLicenseError(
            f"this declaration was already revoked on {status.declaration.revoked_at}"
        )
    revoked = status.declaration.model_copy(
        update={"revoked_at": utc_timestamp(), "revocation_reason": reason}
    )
    save_artifact(revoked, status.path)
    return revoked


def resolve_attestation(
    project_root: str | Path,
    *,
    explicit: RemotionLicenseAttestation | None = None,
) -> tuple[RemotionLicenseAttestation, RemotionLicenseSource]:
    """Apply the documented precedence, or stop with the whole instruction."""
    if explicit is not None:
        return explicit, RemotionLicenseSource.CLI_FLAG
    status = declaration_status(project_root)
    if status.usable:
        assert status.declaration is not None  # implied by `usable`
        return status.declaration.attestation, RemotionLicenseSource.PROJECT_DECLARATION
    raise RemotionLicenseError(_gate_message(status))


def _gate_message(status: DeclarationStatus) -> str:
    headline = {
        "absent": "this project has no recorded Remotion license declaration",
        "revoked": "this project's Remotion license declaration was revoked",
        "stale_terms": "this project's Remotion license declaration needs re-confirming",
        "stale_release": "this project's Remotion license declaration needs re-confirming",
        "expired": "this project's Remotion license declaration needs re-confirming",
        "unsupported_version": "this project's Remotion license declaration cannot be read",
        "unreadable": "this project's Remotion license declaration cannot be read",
    }[status.code]
    reconfirm = status.code in {"stale_terms", "stale_release", "expired"}
    action = (
        "social-video-agent remotion-license refresh --project-root PROJECT --accept-terms"
        if reconfirm
        else "social-video-agent remotion-license attest DECLARATION "
        "--project-root PROJECT --accept-terms"
    )
    return "\n".join(
        [
            f"Remotion is the default renderer, but {headline}: {status.detail}.",
            f"File: {status.path}",
            "",
            f"Record one declaration for the project and later edits reuse it:\n  {action}",
            f"DECLARATION is one of: {_CHOICES}.",
            "",
            "Declare free_license_eligible only if you are an individual, a for-profit "
            "organization with up to 3 employees, a non-profit, or evaluating "
            "non-commercially; otherwise obtain a Company License first and declare "
            "company_license_confirmed. This is your statement: the CLI does not decide "
            "eligibility and does not read company size, revenue, or any other data.",
            f"Terms: {REMOTION_LICENSE_URL}",
            "",
            "For one edit only, pass --remotion-license DECLARATION to `workflow init`. "
            "To avoid Remotion entirely, select --renderer ffmpeg.",
        ]
    )


def _parse(value: RemotionLicenseAttestation | str) -> RemotionLicenseAttestation:
    if isinstance(value, RemotionLicenseAttestation):
        return value
    try:
        return RemotionLicenseAttestation(value)
    except ValueError as exc:
        raise RemotionLicenseError(
            f"{value!r} is not a Remotion license declaration; use one of: {_CHOICES}. "
            "No other value is accepted, and eligibility is never inferred."
        ) from exc


def _release_line(version: str) -> str:
    return ".".join(version.split(".")[:2])


def _age_days(declared_at: str) -> int | None:
    try:
        moment = datetime.fromisoformat(declared_at)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - moment) // timedelta(days=1))
