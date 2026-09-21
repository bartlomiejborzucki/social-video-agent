"""The project's recorded Remotion license declaration.

Remotion is source-available, not Apache-2.0, so using it requires the user to
say which license applies to them. That is a statement a person makes, never a
fact this tool derives: nothing here reads company size, revenue, funding, or
any other signal, and there is no field in which such a signal could be
supplied. The model records *what was declared, when, under which build, and
against which terms* -- and nothing else.

The declaration lives beside the project config but in its own file, because
``config.yaml`` is branding and this is a licensing statement with a different
author, a different lifetime, and a different reason to change.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from social_video.schemas.base import Artifact
from social_video.schemas.workflow import RemotionLicenseAttestation

#: The terms the declaration is made against. Recorded in every declaration so
#: a later build can tell that the user agreed to a different page than the one
#: it would show them today.
REMOTION_LICENSE_URL = "https://www.remotion.dev/license"


class RemotionLicenseDeclaration(Artifact):
    """One conscious licensing statement, reusable across edits and sessions."""

    declaration_version: int = 1
    attestation: RemotionLicenseAttestation
    #: False is never written: a declaration without an acknowledgement of the
    #: terms is not a declaration. Kept explicit in the file so the record
    #: shows the acknowledgement rather than implying it.
    terms_acknowledged: bool = False
    license_terms_url: str = REMOTION_LICENSE_URL
    declared_at: str
    #: Who made the statement, when they chose to record it. Optional, never
    #: filled in from the environment or from git.
    declared_by: str | None = None
    #: Free text for the human record. It is never read back as evidence, and
    #: it never affects which license applies.
    note: str | None = None
    #: Component versions at declaration time, so an upgrade can ask again.
    component_versions: dict[str, str] = Field(default_factory=dict)
    revoked_at: str | None = None
    revocation_reason: str | None = None

    @model_validator(mode="after")
    def _requires_a_conscious_statement(self) -> RemotionLicenseDeclaration:
        if not self.terms_acknowledged:
            raise ValueError(
                "a Remotion license declaration requires terms_acknowledged: true; "
                f"read {self.license_terms_url} and declare deliberately"
            )
        if self.revocation_reason and not self.revoked_at:
            raise ValueError("revocation_reason without revoked_at")
        return self

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None
