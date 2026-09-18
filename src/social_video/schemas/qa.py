"""QA reporting.

Checks are mechanical first. Visual inspection is targeted at what the
mechanical checks flag, rather than being the primary mechanism.

Upstream's self-evaluation is prompt text with no implementation: it asks a
vision model to spot a 30 ms audio pop in a filmstrip, and the waveform image
it inspects is normalised per window, which hides exactly the pops it is
looking for.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, computed_field

from social_video.schemas.base import Artifact


class QASeverity(str, Enum):
    #: Definitely wrong. Blocks delivery.
    ERROR = "error"
    #: Probably wrong, or worth a look.
    WARNING = "warning"
    #: Informational measurement.
    INFO = "info"


class QACheck(Artifact):
    """One check and what it found."""

    name: str
    severity: QASeverity
    passed: bool
    message: str
    #: Where in the output this applies, when it is localised.
    at: float | None = Field(default=None, ge=0.0)
    #: Measured value and what was expected, when numeric.
    measured: float | None = None
    expected: float | None = None
    #: Diagnostic image generated for this finding, if any.
    artifact: str | None = None
    accepted: bool = False


class QAReport(Artifact):
    """The result of inspecting one rendered output."""

    output: str = Field(description="Path to the rendered file that was checked.")
    edl: str | None = None
    #: Which repair attempt produced this. Persisted so the loop cannot run away.
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=3, ge=1)
    checks: list[QACheck] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)

    @property
    def errors(self) -> list[QACheck]:
        return [c for c in self.checks if not c.passed and c.severity is QASeverity.ERROR]

    @property
    def warnings(self) -> list[QACheck]:
        return [
            c
            for c in self.checks
            if not c.passed and c.severity is QASeverity.WARNING and not c.accepted
        ]

    @property
    def passed(self) -> bool:
        return not self.errors

    @computed_field
    def status(self) -> str:
        if self.errors:
            return "failed"
        if self.warnings:
            return "passed_with_warnings"
        return "passed"

    @property
    def exhausted(self) -> bool:
        """Whether the repair budget is spent and remaining issues must be reported."""
        return self.attempt >= self.max_attempts


class RenderManifest(Artifact):
    """Exactly what was rendered, and how. Makes a render reproducible."""

    output: str
    edl: str
    rendered_at: str = Field(description="ISO 8601 timestamp.")
    duration: float = Field(ge=0.0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    frame_rate: str
    #: Set when the output rate differs from the source rate, and why.
    frame_rate_converted_from: str | None = None
    video_codec: str = "h264"
    audio_codec: str = "aac"
    crf: int | None = None
    preset: str | None = None
    loudness_target_lufs: float | None = None
    sources_used: list[str] = Field(default_factory=list)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    brand_contract_sha256: str | None = None
    caption_style: dict = Field(default_factory=dict)
    #: Which compositor drew the captions, and which contracted caption features
    #: it actually applied. Recording the intent alone would make brand QA
    #: tautological: it would compare the contract against itself.
    caption_renderer: str = ""
    caption_features: list[str] = Field(default_factory=list)
    captions_burned: bool = False
    logo_applied: bool = False
    #: What was actually mixed under the speech, so policy can be checked
    #: against evidence rather than against the EDL's own intent.
    audio_bed_applied: dict = Field(default_factory=dict)
    sound_effects_applied: int = Field(default=0, ge=0)
    brand_safe_margins: dict[str, float] = Field(default_factory=dict)
