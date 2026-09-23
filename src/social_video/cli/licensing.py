"""The project's Remotion license declaration."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.markup import escape

from social_video.cli._apps import (
    license_app,
)
from social_video.cli._common import _guard, console


@license_app.command("attest")
def remotion_license_attest(
    declaration: str = typer.Argument(
        ..., help="free_license_eligible or company_license_confirmed. Nothing else."
    ),
    project_root: Path = typer.Option(Path(), "--project-root", help="Target project root."),
    accept_terms: bool = typer.Option(
        False,
        "--accept-terms",
        help="Records that you read the linked terms and are declaring this yourself.",
    ),
    declared_by: str | None = typer.Option(None, "--declared-by", help="Who is declaring."),
    note: str | None = typer.Option(None, "--note", help="Kept for the record; never read back."),
    replace: bool = typer.Option(False, "--replace", help="Replace an existing declaration."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Record this project's Remotion license declaration for later sessions."""
    from social_video.remotion_license import attest

    recorded = _guard(
        lambda: attest(
            project_root,
            declaration,
            accept_terms=accept_terms,
            declared_by=declared_by,
            note=note,
            replace=replace,
        )
    )
    _print_license(project_root, recorded.attestation.value, as_json=as_json, action="recorded")


@license_app.command("status")
def remotion_license_status(
    project_root: Path = typer.Option(Path(), "--project-root", help="Target project root."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Report the stored declaration, and whether a workflow may rely on it."""
    from social_video.remotion_license import declaration_status

    status = _guard(lambda: declaration_status(project_root))
    declaration = status.declaration
    payload = {
        "path": str(status.path),
        "present": status.present,
        "usable": status.usable,
        "code": status.code,
        "detail": status.detail,
        "attestation": declaration.attestation.value if declaration else None,
        "declared_at": declaration.declared_at if declaration else None,
        "declared_by": declaration.declared_by if declaration else None,
        "license_terms_url": declaration.license_terms_url if declaration else None,
        "component_versions": declaration.component_versions if declaration else {},
        "revoked_at": declaration.revoked_at if declaration else None,
        "revocation_reason": declaration.revocation_reason if declaration else None,
        "note": declaration.note if declaration else None,
    }
    if as_json:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    mark = "[green]usable[/green]" if status.usable else "[yellow]unusable[/yellow]"
    console.print(f"{mark} {escape(status.path.as_posix())}", soft_wrap=True)
    console.print(f"  {escape(status.detail)}", soft_wrap=True)
    if declaration is not None:
        console.print(f"  declaration: [cyan]{escape(declaration.attestation.value)}[/cyan]")
        console.print(f"  terms: {escape(declaration.license_terms_url)}", soft_wrap=True)
        if declaration.declared_by:
            console.print(f"  declared by: {escape(declaration.declared_by)}")
        versions = ", ".join(f"{k}={v}" for k, v in sorted(declaration.component_versions.items()))
        if versions:
            console.print(f"  declared under: {escape(versions)}", soft_wrap=True)
    console.print("  eligibility is never inferred by this tool; the declaration is yours.")


@license_app.command("refresh")
def remotion_license_refresh(
    project_root: Path = typer.Option(Path(), "--project-root", help="Target project root."),
    accept_terms: bool = typer.Option(
        False, "--accept-terms", help="Re-confirm the terms as they stand today."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Re-confirm the existing declaration against today's terms and build."""
    from social_video.remotion_license import refresh

    recorded = _guard(lambda: refresh(project_root, accept_terms=accept_terms))
    _print_license(project_root, recorded.attestation.value, as_json=as_json, action="refreshed")


@license_app.command("revoke")
def remotion_license_revoke(
    project_root: Path = typer.Option(Path(), "--project-root", help="Target project root."),
    reason: str | None = typer.Option(None, "--reason", help="Why it is withdrawn."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Withdraw the declaration; Remotion workflows stop until it is made again."""
    from social_video.remotion_license import revoke

    recorded = _guard(lambda: revoke(project_root, reason=reason))
    _print_license(project_root, recorded.attestation.value, as_json=as_json, action="revoked")


def _print_license(project_root: Path, attestation: str, *, as_json: bool, action: str) -> None:
    from social_video.remotion_license import declaration_path

    path = declaration_path(project_root)
    if as_json:
        console.print_json(
            json.dumps({"status": action, "attestation": attestation, "path": str(path)})
        )
        return
    console.print(f"[green]{action}[/green] {escape(attestation)} -> {escape(path.as_posix())}")
