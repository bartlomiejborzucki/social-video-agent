"""Environment diagnostics.

Answers one question: will this machine actually produce a correct video? Every
check that fails says what to do about it. Upstream has an open issue asking
for exactly this and an unmerged pull request providing it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from social_video.errors import SocialVideoError
from social_video.ffmpeg.fonts import default_caption_font, describe_coverage
from social_video.ffmpeg.run import (
    ffmpeg_version,
    find_binary,
    has_filter,
    has_libass,
    has_libzimg,
)
from social_video.paths import app_home, is_wsl
from social_video.project_validation import validate_marketplace, validate_plugin, validate_skill


@dataclass
class Check:
    name: str
    ok: bool
    #: False means "this only limits optional functionality".
    required: bool
    detail: str = ""
    #: What the user should actually do. Empty when nothing is wrong.
    remedy: str = ""

    @property
    def status(self) -> str:
        if self.ok:
            return "OK"
        if not self.required:
            return "OPTIONAL" if self.name.startswith("optional:") else "WARNING"
        detail = self.detail.lower()
        return "MISSING" if "missing" in detail or "not found" in detail else "ERROR"


@dataclass
class DoctorReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.required]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and not c.required]

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "summary": "READY" if self.ok else "NOT READY",
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "required": c.required,
                    "detail": c.detail,
                    "remedy": c.remedy,
                }
                for c in self.checks
            ],
        }


def _check_runtime(report: DoctorReport) -> None:
    """Report the agent side and the engine side separately.

    In the hybrid mode these are two machines, and a single "it works" line
    cannot say which half is broken. Each prerequisite gets its own check so a
    missing WSL install, a WSL 1 distribution and a missing engine inside a
    working distribution read differently.
    """
    from social_video.runtime import Problem, RuntimeMode, detect_runtime

    status = detect_runtime()
    report.add(
        Check(
            "runtime mode",
            status.usable,
            status.mode is RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME,
            f"{status.mode.value}"
            + (" (pinned)" if status.explicit else " (detected)")
            + f"; {status.detail}",
            "" if status.usable else status.detail,
        )
    )
    report.add(
        Check(
            "agent environment",
            True,
            False,
            f"agent on {status.agent_platform}; editing engine on "
            f"{status.to_dict()['engine_platform']}",
        )
    )
    if status.mode is not RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME:
        return
    problems = set(status.problems)
    report.add(
        Check(
            "wsl2",
            Problem.WSL_MISSING not in problems and Problem.WSL_BROKEN not in problems,
            True,
            f"{len(status.distributions)} distribution(s) found"
            if status.distributions
            else "wsl.exe unusable",
            "Install WSL2 with `wsl --install`; nothing is installed for you."
            if Problem.WSL_MISSING in problems
            else "",
        )
    )
    report.add(
        Check(
            "wsl distribution",
            status.distribution is not None,
            True,
            f"{status.distribution.name} (WSL {status.distribution.version})"
            if status.distribution
            else status.detail,
            "" if status.distribution else status.detail,
        )
    )
    report.add(
        Check(
            "wsl engine",
            status.engine_version is not None,
            True,
            f"social-video-agent {status.engine_version}"
            if status.engine_version
            else status.detail,
            "" if status.engine_version else status.detail,
        )
    )
    report.add(
        Check(
            "agent-only capabilities",
            True,
            False,
            "native ImageGen and Canva MCP are the agent's own tools and are not "
            "visible from here; the agent must check its own tool list each session",
        )
    )


def _check_platform(report: DoctorReport) -> None:
    system = platform.system()
    detail = (
        f"{system} {platform.release()} ({platform.machine()}), Python {platform.python_version()}"
    )
    if is_wsl():
        detail += " [WSL]"
    report.add(Check("platform", True, False, detail))

    py_ok = sys.version_info >= (3, 10)
    report.add(
        Check(
            "python",
            py_ok,
            True,
            f"Python {platform.python_version()}",
            "" if py_ok else "Python 3.10 or newer is required.",
        )
    )

    if is_wsl():
        distro = os.environ.get("WSL_DISTRO_NAME") or _linux_distribution()
        report.add(
            Check(
                "wsl",
                True,
                False,
                f"WSL detected ({distro})",
            )
        )
    elif system == "Linux":
        report.add(Check("wsl", False, False, "not detected; ordinary Linux is supported"))


def _linux_distribution() -> str:
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.partition("=")[2].strip('"')
    except OSError:
        pass
    return "unknown distribution"


def _check_ffmpeg(report: DoctorReport) -> None:
    try:
        ffmpeg = find_binary("ffmpeg")
    except SocialVideoError as exc:
        report.add(Check("ffmpeg", False, True, "not found", str(exc)))
        report.add(Check("ffprobe", False, True, "not checked", "Install ffmpeg first."))
        return
    report.add(Check("ffmpeg", True, True, f"{ffmpeg} - {ffmpeg_version()}"))

    try:
        report.add(Check("ffprobe", True, True, find_binary("ffprobe")))
    except SocialVideoError as exc:
        report.add(Check("ffprobe", False, True, "not found", str(exc)))

    report.add(
        Check(
            "libass (subtitle burn-in)",
            has_libass(),
            True,
            "available" if has_libass() else "missing",
            ""
            if has_libass()
            else "This ffmpeg cannot burn in captions. On macOS, Homebrew's formula has "
            "shipped without libass: try `brew install ffmpeg --with-libass` or use "
            "`social-video-agent doctor --install-ffmpeg`.",
        )
    )
    report.add(
        Check(
            "libzimg (HDR tone mapping)",
            has_libzimg(),
            False,
            "available" if has_libzimg() else "missing",
            ""
            if has_libzimg()
            else "HDR (HLG/PQ) sources cannot be tone-mapped to SDR without zscale. "
            "SDR sources are unaffected.",
        )
    )
    for filt in ("crop", "scale", "afade", "loudnorm", "overlay", "silencedetect"):
        if not has_filter(filt):
            report.add(
                Check(
                    f"filter {filt}",
                    False,
                    True,
                    "missing",
                    "This ffmpeg build is unusually minimal; install a full build.",
                )
            )


def _check_packages(report: DoctorReport) -> None:
    required = {
        "faster_whisper": "local transcription",
        "scenedetect": "scene detection",
        "cv2": "face-aware reframing",
        "numpy": "signal analysis",
        "PIL": "diagnostic images",
        "fontTools": "font coverage checks",
        "pydantic": "artifact validation",
    }
    for module, purpose in required.items():
        found = importlib.util.find_spec(module) is not None
        report.add(
            Check(
                f"python: {module}",
                found,
                True,
                purpose,
                "" if found else "Reinstall the project: `uv sync` or `pip install -e .`",
            )
        )

    # Reported so the environment is described accurately. Each purpose says
    # what the package is used for, so "ok" never claims a capability that
    # nothing calls.
    optional = {
        "whisperx": (
            "tighter word alignment with `--backend whisperx`",
            "pip install 'social-video-agent[align]'",
        ),
        "pyannote": (
            "speaker diarization (declared; not yet implemented, and the model "
            "weights are gated behind your own Hugging Face token)",
            "pip install 'social-video-agent[diarize]'",
        ),
    }
    for module, (purpose, how) in optional.items():
        found = importlib.util.find_spec(module) is not None
        report.add(Check(f"optional: {module}", found, False, purpose, "" if found else how))


def _check_fonts(report: DoctorReport) -> None:
    font = default_caption_font()
    if font is None:
        report.add(
            Check(
                "caption font",
                False,
                True,
                "none found",
                "No usable caption font. Install one, e.g. "
                "`sudo apt install fonts-noto-core` or `brew install --cask font-inter`.",
            )
        )
        return

    coverage = describe_coverage(font)
    missing = [name for name, ok in coverage.items() if not ok]
    report.add(
        Check(
            "caption font",
            True,
            True,
            f"{font.family} ({font.path})",
        )
    )
    report.add(
        Check(
            "unicode caption coverage",
            not missing,
            True,
            "covers "
            + ", ".join(k for k, v in coverage.items() if v)
            + (f"; MISSING {', '.join(missing)}" if missing else ""),
            ""
            if not missing
            else f"Captions in {', '.join(missing)} would render as empty boxes. "
            f"Install a wider font such as Noto Sans.",
        )
    )


def _check_image_generation(report: DoctorReport) -> None:
    """Cover and end-card plates are optional, so this never fails the report."""
    from social_video.imagegen import detect_image_provider

    status = detect_image_provider()
    report.add(
        Check(
            "image generation",
            True,
            False,
            (
                f"{status.provider.name.value} ({status.provider.model}) via "
                f"{status.provider.credential_env}; {status.provider.cost_note}"
                if status.available and status.provider
                else f"unavailable: {status.reason}"
            ),
            ""
            if status.available
            else "Covers still work: they are composed locally over a real frame.",
        )
    )


def _check_gpu(report: DoctorReport) -> None:
    if os.environ.get("SOCIAL_VIDEO_FORCE_CPU"):
        report.add(Check("gpu", True, False, "CPU MODE (set by SOCIAL_VIDEO_FORCE_CPU)"))
        return
    try:
        import ctranslate2

        count = ctranslate2.get_cuda_device_count()
    except Exception:
        count = 0

    if count == 0:
        report.add(Check("gpu", True, False, "CPU MODE: no CUDA device detected"))
        return

    # A visible CUDA device is not the same as a working one: CTranslate2 needs a
    # matching cuBLAS/cuDNN and only discovers a mismatch when it runs a model.
    usable, why = _cuda_actually_works()
    report.add(
        Check(
            "gpu",
            usable,
            False,
            "GPU AVAILABLE"
            if usable
            else f"CPU MODE: {count} CUDA device(s) visible but not usable: {why}",
            ""
            if usable
            else "Transcription falls back to CPU automatically. To use the GPU, install "
            "cuBLAS and cuDNN matching your CTranslate2 build, or set "
            "SOCIAL_VIDEO_FORCE_CPU=1 to stop trying.",
        )
    )


def _cuda_actually_works() -> tuple[bool, str]:
    """Load the smallest possible CUDA model to prove the stack is complete."""
    try:
        import ctranslate2  # noqa: F401
        from ctranslate2 import get_cuda_device_count

        if get_cuda_device_count() < 1:
            return False, "no device"
        # Probing the libraries directly avoids downloading a model just to check.
        import ctypes

        for lib in ("libcublas.so.12", "libcublas.so.11", "cublas64_12.dll"):
            try:
                ctypes.CDLL(lib)
                return True, ""
            except OSError:
                continue
        return False, "cuBLAS not loadable"
    except Exception as exc:
        return False, str(exc)[:80]


def _check_node(report: DoctorReport) -> None:
    from social_video.remotion_runtime import locate_runtime

    runtime = locate_runtime()
    root = runtime.root if runtime else None
    hint = runtime.install_hint if runtime else "This build does not include the compositor."
    node = shutil.which("node")
    if not node:
        report.add(
            Check(
                "node",
                False,
                True,
                "not found; Remotion is the default renderer",
                "Install Node.js 20+ inside WSL, then rerun `scripts/wsl/bootstrap.sh`.",
            )
        )
    else:
        try:
            version = subprocess.run(
                [node, "--version"], capture_output=True, text=True, timeout=15, check=False
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            version = "unknown"
        try:
            major = int(version.removeprefix("v").split(".", 1)[0])
        except (ValueError, IndexError):
            major = 0
        report.add(
            Check(
                "node",
                major >= 20,
                True,
                f"{version} ({node})",
                "Install Node.js 20+ inside WSL, then rerun `scripts/wsl/bootstrap.sh`."
                if major < 20
                else "",
            )
        )
    npm = shutil.which("npm")
    report.add(
        Check(
            "node package manager",
            npm is not None,
            True,
            npm or "npm not found",
            "Install npm with Node.js inside WSL." if npm is None else "",
        )
    )
    package = root / "package.json" if root else None
    lock = root / "package-lock.json" if root else None
    remotion_package = root / "node_modules" / "remotion" / "package.json" if root else None
    expected = ""
    installed = ""
    if package is not None and remotion_package is not None:
        try:
            expected = json.loads(package.read_text(encoding="utf-8"))["dependencies"]["remotion"]
            installed = json.loads(remotion_package.read_text(encoding="utf-8"))["version"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            pass
    remotion_ok = bool(expected and installed == expected and lock and lock.is_file())
    report.add(
        Check(
            "remotion",
            remotion_ok,
            True,
            f"{installed} (locked)" if remotion_ok else "dependencies not installed or mismatched",
            hint if not remotion_ok else "",
        )
    )
    browser = None
    browser_root = root / "node_modules" / ".remotion" if root else None
    if browser_root and browser_root.is_dir():
        browser = next(
            (
                candidate
                for candidate in browser_root.rglob("chrome-headless-shell*")
                if candidate.is_file() and os.access(candidate, os.X_OK)
            ),
            None,
        )
    report.add(
        Check(
            "remotion browser",
            browser is not None,
            True,
            str(browser) if browser else "Chrome Headless Shell not found",
            hint if browser is None else "",
        )
    )


def _check_python_environment(report: DoctorReport) -> None:
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    report.add(
        Check(
            "project Python environment",
            in_venv,
            False,
            sys.prefix if in_venv else "not running from a virtual environment",
            "Run through `uv run` or rerun `scripts/wsl/bootstrap.sh`." if not in_venv else "",
        )
    )
    uv = shutil.which("uv")
    report.add(
        Check(
            "uv",
            uv is not None,
            False,
            uv or "not found; uv is recommended for installs and development",
            "Install uv from https://docs.astral.sh/uv/getting-started/installation/."
            if not uv
            else "",
        )
    )


def _repository_root() -> Path | None:
    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for path in candidates:
        pyproject = path / "pyproject.toml"
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            continue
        if 'name = "social-video-agent"' in text:
            return path
    return None


def _check_distribution(report: DoctorReport) -> None:
    root = _repository_root()
    if root is None:
        report.add(
            Check(
                "optional: repository metadata",
                False,
                False,
                "installed package; repository files are not available",
            )
        )
        return
    required = ("README.md", "LICENSE", "pyproject.toml", "AGENTS.md")
    missing = [name for name in required if not (root / name).is_file()]
    report.add(
        Check(
            "required project files",
            not missing,
            True,
            "present" if not missing else "missing: " + ", ".join(missing),
        )
    )
    validations = (
        validate_plugin(root),
        validate_plugin(root / "plugins" / "social-video-agent"),
        validate_skill(root / "skills" / "social-video-agent"),
        validate_marketplace(root / ".agents" / "plugins" / "marketplace.json"),
    )
    for index, result in enumerate(validations):
        label = result.name if index == 0 else f"{result.name} ({index + 1})"
        report.add(
            Check(
                label,
                result.ok,
                True,
                "valid" if result.ok else "; ".join(result.errors[:2]),
            )
        )
    from social_video.compatibility import validate_component_versions

    try:
        versions = validate_component_versions(root)
    except Exception as exc:
        report.add(Check("component version compatibility", False, True, str(exc)))
    else:
        report.add(
            Check(
                "component version compatibility",
                True,
                True,
                ", ".join(f"{key}={value}" for key, value in sorted(versions.items())),
            )
        )


def _check_workspace(report: DoctorReport) -> None:
    home = app_home()
    try:
        home.mkdir(parents=True, exist_ok=True)
        probe = home / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        report.add(Check("cache directory", True, True, str(home)))
    except OSError as exc:
        report.add(
            Check(
                "cache directory",
                False,
                True,
                f"{home} is not writable: {exc}",
                "Set SOCIAL_VIDEO_HOME to a writable location.",
            )
        )

    cwd = Path.cwd()
    report.add(
        Check(
            "writable workspace",
            os.access(cwd, os.W_OK),
            True,
            str(cwd) if os.access(cwd, os.W_OK) else f"not writable: {cwd}",
        )
    )


def _check_encoding(report: DoctorReport) -> None:
    """Whether this console can print non-ASCII without crashing."""
    encoding = (sys.stdout.encoding or "").lower()
    ok = "utf" in encoding
    report.add(
        Check(
            "console encoding",
            ok,
            False,
            encoding or "unknown",
            ""
            if ok
            else "This console is not UTF-8, so non-ASCII output may be mangled. On Windows "
            "run `chcp 65001`, or set PYTHONIOENCODING=utf-8.",
        )
    )


def run_doctor() -> DoctorReport:
    """Run every diagnostic."""
    report = DoctorReport()
    _check_runtime(report)
    _check_platform(report)
    _check_python_environment(report)
    _check_encoding(report)
    _check_ffmpeg(report)
    _check_packages(report)
    _check_fonts(report)
    _check_gpu(report)
    _check_image_generation(report)
    _check_node(report)
    _check_workspace(report)
    _check_distribution(report)
    return report
