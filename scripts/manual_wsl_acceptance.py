#!/usr/bin/env python3
"""Exercise a real WSL-mounted Windows drive without network or ASR models."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from social_video.captions.ass import write_ass
from social_video.edl.render import DRAFT, render_edl
from social_video.ffmpeg.fonts import default_caption_font
from social_video.ffmpeg.probe import probe
from social_video.paths import app_home, is_wsl, is_wsl_mount_path, normalize_user_path
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.edl import EDL, EDLRange
from social_video.sources import build_manifest
from social_video.workspace.layout import Workspace


def _run(argv: list[str]) -> None:
    subprocess.run(argv, check=True, capture_output=True, text=True, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mount-root", type=Path, default=Path("/mnt/c/Temp"))
    args = parser.parse_args()
    mount_root = args.mount_root.resolve()
    if not is_wsl() or not is_wsl_mount_path(mount_root):
        raise SystemExit("ERROR: --mount-root must be a /mnt/<drive> directory inside WSL")
    mount_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="social-video-agent-", dir=mount_root) as tmp:
        mounted = Path(tmp)
        source = mounted / "Mój film testowy 01 ąćęłńóśźż.mp4"
        _run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=640x360:rate=30:duration=1.2",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1.2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "ultrafast",
                "-c:a",
                "aac",
                "-shortest",
                str(source),
            ]
        )
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        windows_source = subprocess.run(
            ["wslpath", "-w", str(source)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        normalized = normalize_user_path(windows_source, must_exist=True)
        if normalized != source:
            raise SystemExit(f"ERROR: path round trip changed: {source} -> {normalized}")

        workspace = Workspace.for_source(windows_source)
        if not workspace.root.is_relative_to(app_home() / "workspaces"):
            raise SystemExit(
                f"ERROR: mounted source workspace is not in Linux cache: {workspace.root}"
            )

        with tempfile.TemporaryDirectory(prefix="social-video-render-") as linux_tmp:
            local = Path(linux_tmp)
            font = default_caption_font()
            captions = write_ass(
                CaptionTrack(
                    language="pl",
                    cues=[CaptionCue(index=1, start=0.05, end=0.9, text="Zażółć gęślą jaźń")],
                ),
                CaptionStyle(),
                local / "napisy.ass",
                width=360,
                height=640,
                font_name=font.family if font else None,
            )
            manifest = build_manifest([normalized])
            edl = EDL(
                output_width=360,
                output_height=640,
                output_fps="30/1",
                ranges=[EDLRange(source=manifest.ids[0], start=0.0, end=1.0)],
            )
            local_output = local / "output.mp4"
            render_edl(edl, manifest, local_output, quality=DRAFT, caption_file=captions)
            mounted_output = mounted / "Gotowy film ąćęłńóśźż.mp4"
            shutil.copy2(local_output, normalize_user_path(mounted_output))
            info = probe(mounted_output)
            if not info.video or not info.video.is_portrait:
                raise SystemExit("ERROR: mounted output is not a portrait video")

        after = hashlib.sha256(source.read_bytes()).hexdigest()
        if before != after:
            raise SystemExit("ERROR: source media changed")
        print(f"READY: real WSL mount accepted {windows_source}")
        print(f"workspace: {workspace.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
