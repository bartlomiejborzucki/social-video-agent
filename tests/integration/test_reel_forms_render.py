"""Hook title, end teaser, picture effects, a prop and an insert, drawn by Remotion."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from social_video.schemas.motion import Effect, MotionElement, MotionPlan
from tests.integration.test_word_synced_render import HEIGHT, WIDTH, pytestmark  # noqa: F401


def _testsrc(tmp_path: Path, seconds: float, name: str = "base.mp4", colour: str = "") -> Path:
    """A moving test pattern, so effects that redraw the picture have one to redraw."""
    path = tmp_path / name
    source = (
        f"color=c={colour}:s={WIDTH}x{HEIGHT}:r=30:d={seconds}"
        if colour
        else (f"testsrc2=s={WIDTH}x{HEIGHT}:r=30:d={seconds}")
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source,
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
        check=True,
    )  # fmt: skip
    return path


def _frames(output: Path, tmp_path: Path):
    def frame(at: float) -> np.ndarray:
        png = tmp_path / f"f-{at:.2f}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(output),
             "-frames:v", "1", str(png)],
            check=True,
        )  # fmt: skip
        with Image.open(png) as image:
            return np.asarray(image.convert("RGB")).astype(int)

    return frame


def test_titles_effects_prop_and_insert_are_drawn(tmp_path: Path) -> None:
    from social_video.remotion import render_motion_design

    seconds = 9.0
    base = _testsrc(tmp_path, seconds)
    red = _testsrc(tmp_path, 3.0, name="insert.mp4", colour="red")
    picture = tmp_path / "okladka.png"
    Image.new("RGB", (300, 400), (20, 200, 40)).save(picture)
    plan = MotionPlan(
        rationale="Every new form once.",
        accent_color="#D0A020",
        elements=[
            MotionElement(type="hook_title", start=0.4, end=2.6, text="Kto pierwszy ustąpi?",
                          secondary_text="część 1.", reason="Title."),
            MotionElement(type="prop", start=3.0, end=4.6, prop="okladka", reason="Prop."),
            MotionElement(type="insert", start=5.0, end=6.0, video_asset=str(red),
                          rights="test pattern", reason="Insert."),
            MotionElement(type="end_teaser", start=6.5, end=9.0, text="Jutro część 2",
                          reason="Teaser."),
        ],
        effects=[Effect(type="tilt", start=2.8, end=4.8, reason="Tilt."),
                 Effect(type="bw_flash", start=6.2, end=6.5, reason="Flash.")],
    )  # fmt: skip
    output, _features, _layout = render_motion_design(
        base, tmp_path / "out.mp4", plan,
        duration_in_frames=round(seconds * 30), fps=30, width=WIDTH, height=HEIGHT,
        staging_root=tmp_path / "stage", props_library={"okladka": picture},
    )  # fmt: skip
    frame = _frames(output, tmp_path)
    (tmp_path / "plain").mkdir()
    plain = _frames(base, tmp_path / "plain")

    def drawn(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.abs(a - b).mean())

    def band(at: float, top: float, bottom: float) -> float:
        rows = slice(round(HEIGHT * top), round(HEIGHT * bottom))
        return drawn(frame(at)[rows], plain(at)[rows])

    # Re-encoding alone moves a test pattern this much; frame 0 is the scene.
    noise = band(0.0, 0.0, 1.0)
    # The title is drawn over the top of the picture, and gone by the end.
    assert band(1.5, 0.05, 0.3) > noise + 8
    # The prop's green sits in the middle of the tilted frame.
    middle = frame(4.0)[HEIGHT // 3 : 2 * HEIGHT // 3, WIDTH // 3 : 2 * WIDTH // 3]
    greenish = (middle[..., 1] > 150) & (middle[..., 0] < 90) & (middle[..., 2] < 110)
    assert greenish.mean() > 0.5
    # The insert fills the frame with its own (red) picture.
    insert = frame(5.5)
    assert (insert[..., 0] > 180).mean() > 0.9 and insert[..., 1].mean() < 60
    # The flash takes the colour out: every pixel is grey.
    flash = frame(6.35)
    assert np.abs(flash[..., 0] - flash[..., 1]).mean() < 6
    # The teaser sits at half height over the live picture.
    assert band(8.0, 0.48, 0.58) > noise + 8
