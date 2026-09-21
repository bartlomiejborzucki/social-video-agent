"""What Stage 0 found out about the two machines it has to work across.

Written once per edit and read on resume. The durable half -- which platform the
agent is on, which WSL distribution holds the engine, where the project lives on
each side, which binaries exist -- is a property of the installation and is
safe to trust later.

The other half is not. A native image tool and an MCP connection to Canva
belong to the *session* that had them: the same project opened tomorrow, or from
a different agent, may have neither. Those live in their own block, marked
session-scoped, so nothing later mistakes yesterday's tool list for a fact about
the project.
"""

from __future__ import annotations

from pydantic import Field

from social_video.schemas.base import Artifact
from social_video.schemas.visuals import CapabilityState


class ToolAvailability(Artifact):
    """Which engine-side binaries Stage 0 could actually run."""

    cli: bool = False
    ffmpeg: bool = False
    ffprobe: bool = False
    python: bool = False
    node: bool = False
    remotion: bool = False
    local_transcription: bool = False


class SessionCapabilities(Artifact):
    """Capabilities that expire with the session that observed them.

    Recorded so the agent can say what it used, never so a later run can skip
    checking. Both default to ``unknown_to_cli`` because no Python process can
    see either one.
    """

    native_imagegen: CapabilityState = CapabilityState.UNKNOWN_TO_CLI
    canva: CapabilityState = CapabilityState.UNKNOWN_TO_CLI
    #: Always true, and stated in the artifact rather than only in this
    #: docstring, so a reader of the JSON sees it too.
    session_scoped: bool = True
    recheck_on_resume: str = (
        "Re-check the agent's own tool list when resuming; these are not project facts."
    )


class RuntimeRecord(Artifact):
    """Stage 0's picture of where the agent is and where the editing happens."""

    runtime_mode: str
    agent_platform: str
    engine_platform: str
    wsl_distribution: str | None = None
    wsl_version: int | None = None
    engine_version: str | None = None
    #: The project as the agent sees it, when that differs from the Linux path.
    windows_project_path: str | None = None
    #: The project as the engine sees it. Always a Linux path.
    project_path: str
    #: Where heavy intermediates go: a Linux directory, never a synced folder.
    cache_root: str
    tools: ToolAvailability = Field(default_factory=ToolAvailability)
    session: SessionCapabilities = Field(default_factory=SessionCapabilities)
    image_generation_policy: str = "none"
    remotion_license_attestation: str | None = None
    recorded_at: str
    problems: list[str] = Field(default_factory=list)
