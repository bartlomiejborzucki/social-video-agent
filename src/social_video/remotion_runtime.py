"""Find, and for an installed package set up, the pinned Remotion compositor.

The compositor is this project's own code -- the React compositions, the render
script, and the npm manifest and lockfile that pin Remotion. It lives in one of
two places:

* a repository checkout, where ``scripts/wsl/bootstrap.sh`` has already run
  ``npm ci`` next to the sources, exactly as before; or
* an installed wheel, which carries the same files as package data under
  ``social_video/_remotion``. Those are copied into the app cache and
  ``npm ci`` runs there, so ``site-packages`` is never written to.

Remotion itself is never shipped in the wheel. Its npm packages are installed
from the registry on the user's machine, under the Stage 0 licence declaration,
which is the same arrangement the checkout has always had.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from social_video import __version__
from social_video.errors import SocialVideoError, ToolNotFoundError
from social_video.paths import is_wsl_mount_path, tools_dir

#: Everything the compositor needs, relative to its root. The wheel's
#: ``force-include`` table in ``pyproject.toml`` must list the same paths.
ASSETS = (
    "remotion",
    "scripts/remotion/render.mjs",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
)

_BUNDLED = Path(__file__).resolve().parent / "_remotion"


@dataclass(frozen=True)
class RemotionRuntime:
    root: Path
    from_checkout: bool

    @property
    def script(self) -> Path:
        return self.root / "scripts" / "remotion" / "render.mjs"

    @property
    def entry(self) -> Path:
        return self.root / "remotion" / "index.ts"

    @property
    def dependencies_installed(self) -> bool:
        return (self.root / "node_modules" / "remotion").is_dir()

    @property
    def locked_version(self) -> str:
        """The Remotion version this compositor pins, as ``package.json`` states it."""
        import json

        manifest = self.root / "package.json"
        if not manifest.is_file():
            manifest = _BUNDLED / "package.json"
        try:
            return str(json.loads(manifest.read_text(encoding="utf-8"))["dependencies"]["remotion"])
        except (OSError, KeyError, TypeError, ValueError):
            return "unknown"

    @property
    def install_hint(self) -> str:
        if self.from_checkout:
            return (
                "Run `npm ci`, then `npx remotion browser ensure`, in the Linux "
                "repository checkout (or rerun `scripts/wsl/bootstrap.sh`)."
            )
        return "Run `social-video-agent doctor --install-remotion`."


def _has_assets(root: Path) -> bool:
    return all((root / asset).exists() for asset in ASSETS)


def _checkout_root() -> Path | None:
    root = Path(__file__).resolve().parents[2]
    return root if _has_assets(root) else None


def installed_root() -> Path:
    """Where an installed package keeps its compositor, one per release."""
    return tools_dir() / "remotion" / __version__


def locate_runtime() -> RemotionRuntime | None:
    """The compositor this build uses, installed or not; ``None`` if absent."""
    checkout = _checkout_root()
    if checkout is not None:
        return RemotionRuntime(checkout, from_checkout=True)
    if _has_assets(_BUNDLED):
        return RemotionRuntime(installed_root(), from_checkout=False)
    return None


def install_runtime() -> RemotionRuntime:
    """Install the compositor's locked npm dependencies and headless browser.

    For an installed package the bundled files are staged next to the target
    and moved into place only once ``npm ci`` and the browser download have
    both succeeded, so an interrupted install never looks usable.
    """
    runtime = locate_runtime()
    if runtime is None:
        raise ToolNotFoundError("this build does not include the Remotion compositor")
    npm = shutil.which("npm")
    npx = shutil.which("npx")
    if npm is None or npx is None:
        raise ToolNotFoundError(
            "npm was not found inside the WSL/Linux environment; install Node.js 20+ first"
        )
    if is_wsl_mount_path(runtime.root):
        raise SocialVideoError(
            f"refusing to install Remotion under {runtime.root}: Node installs and renders "
            "on a mounted Windows drive are slow and unreliable. Set SOCIAL_VIDEO_HOME "
            "to a path inside the WSL filesystem."
        )
    if runtime.from_checkout:
        _npm_install(runtime.root, npm, npx)
        return runtime

    target = runtime.root
    staging = target.with_name(f".{target.name}.{uuid4().hex}.partial")
    try:
        staging.mkdir(parents=True)
        for asset in ASSETS:
            source = _BUNDLED / asset
            destination = staging / asset
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        _npm_install(staging, npm, npx)
        if target.exists():
            shutil.rmtree(target)
        staging.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return runtime


def _npm_install(root: Path, npm: str, npx: str) -> None:
    for args, desc in (
        ([npm, "ci", "--no-audit", "--no-fund"], "npm ci"),
        ([npx, "--no-install", "remotion", "browser", "ensure"], "remotion browser ensure"),
    ):
        proc = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            check=False,
        )
        if proc.returncode != 0:
            detail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-20:])
            raise SocialVideoError(f"{desc} failed (exit {proc.returncode}):\n{detail}")
