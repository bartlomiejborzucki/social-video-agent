"""Which machine the agent runs on, and which machine does the editing.

Two machines, two jobs. The *agent* may be a native Windows Codex process with
tools of its own -- ImageGen, a Canva MCP connection, Windows Chrome. The
*engine* is always a Linux one: FFmpeg, FFprobe, Python, Node, Remotion, its
Chromium and local transcription live inside WSL2 and stay there. Mixing a
Windows binary into a Linux render is how a pipeline ends up with two different
colour conversions and one broken font path, so a single run never does it.

Supported modes:

``wsl-native``
    The agent and the engine are both inside WSL. This is the original mode and
    nothing about it changes.
``windows-agent-wsl-runtime``
    The agent is a native Windows process; every editing operation is delegated
    into a WSL2 distribution through the adapter in ``scripts/windows``.
``linux-native`` / ``macos-native``
    One machine, no boundary. Unchanged.

Detection never consults a terminal preference. Which shell a GUI opens says
nothing about where the agent process itself is running, and the two are
configured separately. The facts used are: the real platform of this process,
whether ``wsl.exe`` can be executed, whether the chosen distribution reports
WSL 2, and whether the engine is installed inside it. Anything unknowable from
here is reported as unknown rather than assumed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

#: Environment overrides. A project config may also pin both; the environment
#: wins so one session can be redirected without editing a shared file.
MODE_ENV = "SOCIAL_VIDEO_RUNTIME_MODE"
DISTRIBUTION_ENV = "SOCIAL_VIDEO_WSL_DISTRIBUTION"

#: The engine executable, looked for inside the distribution.
ENGINE_COMMAND = "social-video-agent"

#: WSL 1 cannot run this engine usefully: it has no real kernel, so the
#: FFmpeg/Remotion stack and the /proc interfaces we probe behave differently.
MINIMUM_WSL_VERSION = 2


class RuntimeMode(str, Enum):
    WSL_NATIVE = "wsl-native"
    WINDOWS_AGENT_WSL_RUNTIME = "windows-agent-wsl-runtime"
    LINUX_NATIVE = "linux-native"
    MACOS_NATIVE = "macos-native"


class Problem(str, Enum):
    """Each failure a hybrid session can have, kept distinguishable.

    A single "it does not work" message is useless here: the fix for a missing
    WSL install, a WSL 1 distribution and a missing engine inside a working
    distribution are three different actions.
    """

    WSL_MISSING = "wsl_missing"
    WSL_BROKEN = "wsl_broken"
    NO_DISTRIBUTION = "no_distribution"
    DISTRIBUTION_NOT_FOUND = "distribution_not_found"
    WSL1_ONLY = "wsl1_only"
    ENGINE_MISSING = "engine_missing"
    ENGINE_BROKEN = "engine_broken"
    UNSUPPORTED_PLATFORM = "unsupported_platform"


@dataclass(frozen=True)
class Distribution:
    name: str
    version: int
    default: bool = False

    @property
    def is_wsl2(self) -> bool:
        return self.version >= MINIMUM_WSL_VERSION


@dataclass(frozen=True)
class RuntimeStatus:
    """Where the agent is, where the engine is, and what is missing."""

    mode: RuntimeMode
    agent_platform: str
    #: Set only in the hybrid mode.
    distribution: Distribution | None = None
    distributions: tuple[Distribution, ...] = ()
    engine_version: str | None = None
    problems: tuple[Problem, ...] = ()
    detail: str = ""
    #: True when the mode was pinned rather than detected.
    explicit: bool = False

    @property
    def usable(self) -> bool:
        return not self.problems

    @property
    def hybrid(self) -> bool:
        return self.mode is RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "agent_platform": self.agent_platform,
            "engine_platform": "wsl"
            if self.hybrid or self.mode is RuntimeMode.WSL_NATIVE
            else self.agent_platform,
            "wsl_distribution": self.distribution.name if self.distribution else None,
            "wsl_version": self.distribution.version if self.distribution else None,
            "distributions_found": [
                {"name": item.name, "version": item.version, "default": item.default}
                for item in self.distributions
            ],
            "engine_version": self.engine_version,
            "usable": self.usable,
            "problems": [item.value for item in self.problems],
            "detail": self.detail,
            "explicit": self.explicit,
        }


@dataclass
class Probes:
    """Everything detection needs from the outside world, so it can be faked.

    Windows and WSL cannot be installed inside a test, and a test that shells
    out to the real ``wsl.exe`` would only pass on one developer's laptop.
    """

    platform: str = field(default_factory=lambda: sys.platform)
    inside_wsl: Callable[[], bool] | None = None
    which: Callable[[str], str | None] = shutil.which
    run: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] | None = None

    def wsl_binary(self) -> str | None:
        return self.which("wsl.exe") or self.which("wsl")

    def is_inside_wsl(self) -> bool:
        if self.inside_wsl is not None:
            return self.inside_wsl()
        from social_video.paths import is_wsl

        return is_wsl()

    def execute(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if self.run is not None:
            return self.run(argv)
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )


def detect_runtime(
    *,
    env: Mapping[str, str] | None = None,
    configured_mode: str | None = None,
    configured_distribution: str | None = None,
    probes: Probes | None = None,
) -> RuntimeStatus:
    """Work out the runtime mode from facts, not from preferences."""
    environment = os.environ if env is None else env
    probe = probes or Probes()
    requested = (environment.get(MODE_ENV) or configured_mode or "").strip().casefold()
    distribution = (
        environment.get(DISTRIBUTION_ENV) or configured_distribution or ""
    ).strip() or None

    if requested in {"", "auto", "detect"}:
        mode, explicit = _detected_mode(probe), False
    else:
        try:
            mode, explicit = RuntimeMode(requested), True
        except ValueError:
            supported = ", ".join(item.value for item in RuntimeMode)
            return RuntimeStatus(
                mode=_detected_mode(probe),
                agent_platform=probe.platform,
                problems=(Problem.UNSUPPORTED_PLATFORM,),
                detail=(
                    f"{MODE_ENV}/runtime_mode={requested!r} is not a runtime mode "
                    f"(expected auto, {supported})"
                ),
            )

    if mode is RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME:
        return _hybrid_status(probe, distribution, explicit=explicit)
    return RuntimeStatus(
        mode=mode,
        agent_platform=probe.platform,
        detail=_single_machine_detail(mode, probe),
        explicit=explicit,
    )


def _detected_mode(probe: Probes) -> RuntimeMode:
    if probe.platform == "win32":
        return RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME
    if probe.platform == "darwin":
        return RuntimeMode.MACOS_NATIVE
    return RuntimeMode.WSL_NATIVE if probe.is_inside_wsl() else RuntimeMode.LINUX_NATIVE


def _single_machine_detail(mode: RuntimeMode, probe: Probes) -> str:
    if mode is RuntimeMode.WSL_NATIVE:
        return "agent and engine both inside WSL; no boundary to cross"
    return f"agent and engine both on {probe.platform}; no boundary to cross"


def _hybrid_status(
    probe: Probes, requested_distribution: str | None, *, explicit: bool
) -> RuntimeStatus:
    """Check the Windows -> WSL2 path, one prerequisite at a time."""
    binary = probe.wsl_binary()
    if binary is None:
        return RuntimeStatus(
            mode=RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME,
            agent_platform=probe.platform,
            problems=(Problem.WSL_MISSING,),
            detail=(
                "wsl.exe was not found, so the editing engine cannot be reached. Install "
                "WSL2 and a distribution (`wsl --install`), then rerun. Nothing is "
                "installed on your behalf."
            ),
            explicit=explicit,
        )
    listing = probe.execute([binary, "--list", "--verbose"])
    if listing.returncode != 0:
        return RuntimeStatus(
            mode=RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME,
            agent_platform=probe.platform,
            problems=(Problem.WSL_BROKEN,),
            detail=(
                "wsl.exe exists but `wsl --list --verbose` failed: "
                f"{_tail(listing.stderr or listing.stdout)}"
            ),
            explicit=explicit,
        )
    found = parse_distributions(listing.stdout)
    if not found:
        return RuntimeStatus(
            mode=RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME,
            agent_platform=probe.platform,
            problems=(Problem.NO_DISTRIBUTION,),
            detail=(
                "WSL is installed but has no distribution. Install one with "
                "`wsl --install -d Ubuntu`."
            ),
            explicit=explicit,
        )
    chosen, problem, detail = _choose_distribution(found, requested_distribution)
    if chosen is None or problem is not None:
        return RuntimeStatus(
            mode=RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME,
            agent_platform=probe.platform,
            distributions=found,
            problems=(problem,) if problem else (),
            detail=detail,
            explicit=explicit,
        )
    version = probe.execute(
        [binary, "--distribution", chosen.name, "--", ENGINE_COMMAND, "version"]
    )
    if version.returncode != 0:
        output = _tail(version.stderr or version.stdout)
        missing = "not found" in output.casefold() or "no such file" in output.casefold()
        return RuntimeStatus(
            mode=RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME,
            agent_platform=probe.platform,
            distribution=chosen,
            distributions=found,
            problems=(Problem.ENGINE_MISSING if missing else Problem.ENGINE_BROKEN,),
            detail=(
                f"`{ENGINE_COMMAND}` is not usable inside {chosen.name}: {output}. Install the "
                "engine in that distribution (./scripts/wsl/bootstrap.sh in the repository); "
                "do not install FFmpeg, Node or Python on the Windows side."
            ),
            explicit=explicit,
        )
    return RuntimeStatus(
        mode=RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME,
        agent_platform=probe.platform,
        distribution=chosen,
        distributions=found,
        engine_version=(version.stdout or "").strip() or None,
        detail=f"agent on Windows, engine in {chosen.name} (WSL {chosen.version})",
        explicit=explicit,
    )


def parse_distributions(listing: str) -> tuple[Distribution, ...]:
    """Parse `wsl --list --verbose`.

    The output is UTF-16 with a marker column, and its header is localised, so
    the header is skipped positionally rather than matched by name.
    """
    distributions: list[Distribution] = []
    for raw in listing.replace("\\x00", "").splitlines():
        line = raw.strip()
        if not line:
            continue
        default = line.startswith("*")
        line = line.lstrip("*").strip()
        parts = line.split()
        if len(parts) < 3 or not parts[-1].isdigit():
            # The header row, or a wrapped diagnostic line.
            continue
        name = " ".join(parts[:-2])
        try:
            version = int(parts[-1])
        except ValueError:
            continue
        if name:
            distributions.append(Distribution(name=name, version=version, default=default))
    return tuple(distributions)


def _choose_distribution(
    found: tuple[Distribution, ...], requested: str | None
) -> tuple[Distribution | None, Problem | None, str]:
    """Pick the distribution without guessing.

    An explicit name is honoured exactly. Otherwise the WSL default is used,
    and a single WSL2 distribution counts as unambiguous. Two candidates with
    no default and no configuration is an ambiguity the user has to settle:
    picking one silently would run the edit on a machine they did not choose.
    """
    if requested:
        named = next((item for item in found if item.name.casefold() == requested.casefold()), None)
        if named is None:
            names = ", ".join(item.name for item in found) or "none"
            return (
                None,
                Problem.DISTRIBUTION_NOT_FOUND,
                f"the configured WSL distribution {requested!r} is not installed (found: {names})",
            )
        if not named.is_wsl2:
            return (
                None,
                Problem.WSL1_ONLY,
                f"{named.name} is WSL {named.version}; the engine needs WSL 2. "
                f"Convert it with `wsl --set-version {named.name} 2`.",
            )
        return named, None, ""
    modern = [item for item in found if item.is_wsl2]
    if not modern:
        names = ", ".join(f"{item.name} (WSL {item.version})" for item in found)
        return (
            None,
            Problem.WSL1_ONLY,
            f"no WSL 2 distribution is installed: {names}. Convert one with "
            "`wsl --set-version <name> 2`.",
        )
    default = next((item for item in modern if item.default), None)
    if default is not None:
        return default, None, ""
    if len(modern) == 1:
        return modern[0], None, ""
    names = ", ".join(item.name for item in modern)
    return (
        None,
        Problem.NO_DISTRIBUTION,
        f"several WSL 2 distributions are installed ({names}) and none is the default. "
        f"Name one with wsl_distribution in the project config or {DISTRIBUTION_ENV}; "
        "choosing one for you would run the edit on a machine you did not pick.",
    )


def _tail(text: str, lines: int = 4) -> str:
    return " ".join((text or "").strip().splitlines()[-lines:]).strip()
