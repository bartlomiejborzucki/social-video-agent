"""Environment diagnostics.

Answers one question: will this machine actually produce a correct video? Every
check that fails says what to do about it. Upstream has an open issue asking
for exactly this and an unmerged pull request providing it.
"""

from __future__ import annotations

import importlib.util
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
from social_video.paths import app_home


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
            return "ok"
        return "fail" if self.required else "warn"


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


def _check_platform(report: DoctorReport) -> None:
    system = platform.system()
    detail = (
        f"{system} {platform.release()} ({platform.machine()}), Python {platform.python_version()}"
    )
    if _is_wsl():
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

    if _is_wsl():
        report.add(
            Check(
                "wsl-media-path",
                True,
                False,
                "Running under WSL",
                "Media on /mnt/c is many times slower to read than media in the Linux "
                "filesystem. For long sources, copy them under ~ first.",
            )
        )


def _is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


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
            "`social-video doctor --install-ffmpeg`.",
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

    optional = {
        "whisperx": ("tighter word alignment", "pip install 'social-video-agent[align]'"),
        "pyannote": ("speaker diarization", "pip install 'social-video-agent[diarize]'"),
        "requests": ("cloud transcription providers", "pip install 'social-video-agent[cloud]'"),
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
            False,
            "covers "
            + ", ".join(k for k, v in coverage.items() if v)
            + (f"; MISSING {', '.join(missing)}" if missing else ""),
            ""
            if not missing
            else f"Captions in {', '.join(missing)} would render as empty boxes. "
            f"Install a wider font such as Noto Sans.",
        )
    )


def _check_gpu(report: DoctorReport) -> None:
    if os.environ.get("SOCIAL_VIDEO_FORCE_CPU"):
        report.add(Check("gpu", True, False, "disabled by SOCIAL_VIDEO_FORCE_CPU"))
        return
    try:
        import ctranslate2

        count = ctranslate2.get_cuda_device_count()
    except Exception:
        count = 0

    if count == 0:
        report.add(Check("gpu", True, False, "none detected; transcription will run on CPU"))
        return

    # A visible CUDA device is not the same as a working one: CTranslate2 needs a
    # matching cuBLAS/cuDNN and only discovers a mismatch when it runs a model.
    usable, why = _cuda_actually_works()
    report.add(
        Check(
            "gpu",
            usable,
            False,
            f"{count} CUDA device(s); {'usable' if usable else 'NOT usable: ' + why}",
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
    node = shutil.which("node")
    if not node:
        report.add(
            Check(
                "optional: node",
                False,
                False,
                "not found; needed only for Remotion motion graphics",
                "Install Node.js 20+ only if you want the optional Remotion visuals.",
            )
        )
        return
    try:
        version = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=15, check=False
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        version = "unknown"
    report.add(Check("optional: node", True, False, f"{version} ({node})"))


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
    _check_platform(report)
    _check_encoding(report)
    _check_ffmpeg(report)
    _check_packages(report)
    _check_fonts(report)
    _check_gpu(report)
    _check_node(report)
    _check_workspace(report)
    return report
