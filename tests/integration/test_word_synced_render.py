"""Graphics synced to the spoken word, drawn by Remotion over a black frame."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from social_video.schemas.motion import MotionElement, MotionPlan
from tests.conftest import requires_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
HAS_REMOTION = shutil.which("node") is not None and (ROOT / "node_modules/.remotion").is_dir()
WIDTH, HEIGHT = 360, 640

pytestmark = [
    pytest.mark.integration,
    requires_ffmpeg,
    pytest.mark.skipif(not HAS_REMOTION, reason="Remotion dependencies/browser not installed"),
]


def _black(tmp_path: Path, seconds: float) -> Path:
    base = tmp_path / "black.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r=30:d={seconds}",
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-t", f"{seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(base)],
        check=True,
    )  # fmt: skip
    return base


def _render(tmp_path: Path, plan: MotionPlan, seconds: float = 4.0, **options):
    from social_video.remotion import render_motion_design

    output, features, _layout = render_motion_design(
        _black(tmp_path, seconds),
        tmp_path / "out.mp4",
        plan,
        duration_in_frames=round(seconds * 30),
        fps=30,
        width=WIDTH,
        height=HEIGHT,
        staging_root=tmp_path / "stage",
        **options,
    )

    def frame(at: float) -> np.ndarray:
        png = tmp_path / f"f-{at:.2f}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(output),
             "-frames:v", "1", str(png)],
            check=True,
        )  # fmt: skip
        with Image.open(png) as image:
            return np.asarray(image.convert("RGB")).astype(int)

    return frame, features


def test_list_points_enter_on_their_word_times(tmp_path: Path) -> None:
    listed = MotionElement(
        type="list", start=0.3, end=3.8, text="Spróbuj tak", items=["Kąpiel", "Bajka"],
        position="top", item_times=[1.0, 2.5], reason="Each point as it is said.",
    )  # fmt: skip
    frame, _ = _render(tmp_path, MotionPlan(rationale="Anchored list.", elements=[listed]))

    def change(a: float, b: float) -> float:
        return float(np.abs(frame(a) - frame(b)).mean())

    # Each point waits for its word (an even reveal would show the first at
    # 0.3 s and the second at 1.5 s), and nothing moves between the words.
    assert change(0.8, 1.9) > 0.2
    assert change(1.9, 2.4) < 0.05
    assert change(2.4, 3.0) > 0.2
    assert change(3.3, 3.5) < 0.05


def test_words_not_spoken_yet_are_dimmed_mid_caption(tmp_path: Path) -> None:
    from social_video.schemas.brand import CaptionStyle
    from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord

    spoken = [("mama", 0.0, 1.0), ("tata", 1.0, 2.0), ("baba", 2.0, 3.0)]
    track = CaptionTrack(
        cues=[
            CaptionCue(index=1, start=0.0, end=3.0, text="mama tata baba",
                       words=[CaptionWord(text=w, start=s, end=e) for w, s, e in spoken])
        ]
    )  # fmt: skip
    style = CaptionStyle(
        primary_colour="#FFFFFF", highlight_active_word=True, highlight_colour="#FFD400",
        upcoming_word_opacity=0.4, font_size_pct=6.0, max_lines=1, outline_width=0,
    )  # fmt: skip
    frame, features = _render(
        tmp_path, MotionPlan(rationale="Caption check."), seconds=3.0,
        captions=track, caption_style=style,
    )  # fmt: skip
    assert "upcoming_words_dimmed" in features

    pixels = frame(1.5)
    drawn = pixels.max(axis=-1) > 60
    columns = np.flatnonzero(drawn.any(axis=0))
    # The words are the runs of drawn columns between the two widest gaps.
    gaps = np.argsort(np.diff(columns))[-2:]
    words = np.split(columns, sorted(gaps + 1))
    said, current, coming = (pixels[:, part][drawn[:, part]] for part in words)
    # Before the current word: full white. The current word: the highlight.
    # After it: the caption colour at 40 %, so no pixel reaches full white.
    assert np.percentile(said.min(axis=-1), 90) > 200
    core = current[current.max(axis=-1) > 180]
    assert (core[:, 2] < core[:, 0] - 80).mean() > 0.9  # yellow: blue far under red
    assert (current.min(axis=-1) > 200).mean() < 0.02  # and nothing white
    assert coming.max() < 140
    # Once it is said, the last word is drawn at full strength.
    assert np.percentile(frame(2.95)[:, words[2]].max(axis=-1), 99.5) > 200


def test_a_strike_is_crossed_out_in_the_accent_then_replaced(tmp_path: Path) -> None:
    strike = MotionElement(
        type="strike", start=0.3, end=3.8, text="Nie płacz!", replacement="Widzę, że ci smutno.",
        strike_at=1.2, replace_at=2.2, strike_mark="cross", reason="The habit, crossed out.",
    )  # fmt: skip
    plan = MotionPlan(rationale="Strike.", accent_color="#D23150", elements=[strike])
    frame, _ = _render(tmp_path, plan)

    def accent(pixels: np.ndarray) -> int:
        red = (pixels[..., 0] > 170) & (pixels[..., 1] < 90) & (pixels[..., 2] < 120)
        return int(red[: HEIGHT // 3].sum())

    def change(a: float, b: float) -> float:
        return float(np.abs(frame(a) - frame(b)).mean())

    # No stroke before its moment; a stroke and a cross in the accent after it.
    assert accent(frame(1.0)) < 5
    assert accent(frame(1.9)) > 60
    # The replacement takes the line's place, and the stroke goes with it.
    assert change(1.9, 3.0) > 0.3
    assert accent(frame(3.0)) < 5


def test_a_bubble_pops_in_over_the_head_on_its_word(tmp_path: Path) -> None:
    bubble = MotionElement(
        type="bubble", start=1.0, end=3.0, text="Jeszcze jedna bajka!", tail="left",
        reason="The child's line.",
    )  # fmt: skip
    message = MotionElement(
        type="bubble", start=3.0, end=4.3, variant="message", text="Co robić, gdy krzyczy?",
        secondary_text="pytanie od obserwatorki", reason="The question that opens a Q&A.",
    )  # fmt: skip
    plan = MotionPlan(rationale="Bubbles.", accent_color="#D23150", elements=[bubble, message])
    frame, _ = _render(tmp_path, plan, seconds=4.5)

    def white(pixels: np.ndarray, rows: slice) -> int:
        return int((pixels[rows].min(axis=-1) > 230).sum())

    upper, lower = slice(0, HEIGHT // 3), slice(HEIGHT // 3, HEIGHT)
    assert white(frame(0.8), upper) == 0
    assert white(frame(1.6), upper) > 2000
    # Over the head only: nothing reaches the middle or the caption band.
    assert white(frame(1.6), lower) == 0
    # The message shows its notification dot in the accent.
    shown = frame(3.8)[upper]
    assert ((shown[..., 0] > 170) & (shown[..., 1] < 90) & (shown[..., 2] < 120)).sum() > 20


def test_an_icon_pops_in_over_the_head_in_the_brand_colours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A local stand-in for the downloaded set: tests never fetch.
    svg = tmp_path / "bath.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="4"><path d="M3 12h18M12 3v18"/></svg>',
        encoding="utf-8",
    )
    monkeypatch.setattr("social_video.motion.icons.icon_file", lambda name, directory=None: svg)
    icon = MotionElement(type="icon", start=1.0, end=2.0, icon="bath", reason="The bath.")
    frame, _ = _render(tmp_path, MotionPlan(rationale="Icon.", accent_color="#D23150",
                                            elements=[icon]), seconds=2.5)  # fmt: skip

    def drawn(pixels: np.ndarray) -> np.ndarray:
        return pixels.max(axis=-1) > 60

    assert not drawn(frame(0.8)).any()
    shown = frame(1.6)
    rows = np.flatnonzero(drawn(shown).any(axis=1))
    # A disc over the head: in the top zone only, with the icon's strokes in
    # the brand's second colour (dark) on white, inside an accent rim.
    assert rows.min() > 0.1 * HEIGHT and rows.max() < 0.25 * HEIGHT
    disc = shown[rows.min() : rows.max() + 1]
    assert ((disc[..., 0] > 170) & (disc[..., 1] < 90) & (disc[..., 2] < 120)).sum() > 20
    centre = shown[int(0.17 * HEIGHT) - 2 : int(0.17 * HEIGHT) + 3, WIDTH // 2 - 2 : WIDTH // 2 + 3]
    assert centre.max() < 120  # the stroke crossing the middle, not the white disc


def test_a_process_fills_stage_by_stage_then_closes_with_a_tick(tmp_path: Path) -> None:
    process = MotionElement(
        type="process", start=0.3, end=4.4, text="Wieczorem", items=["kolacja", "kąpiel", "sen"],
        item_times=[0.6, 1.4, 2.0], done_text="gotowe do snu", reason="The routine.",
    )  # fmt: skip
    plan = MotionPlan(rationale="Process.", accent_color="#28BCA5", elements=[process])
    frame, _ = _render(tmp_path, plan, seconds=4.5, secondary_colour="#394463",
                       brand_colours=["#28BCA5", "#394463", "#D23150"])  # fmt: skip

    def stage_colours(pixels: np.ndarray) -> tuple[int, int]:
        top = pixels[: HEIGHT // 3]
        teal = (np.abs(top - [40, 188, 165]).sum(axis=-1) < 60).sum()
        red = (np.abs(top - [210, 49, 80]).sum(axis=-1) < 60).sum()
        return int(teal), int(red)

    # The first stage (teal) is in before the second (red, the card's own
    # colour skipped) enters on its word.
    teal, red = stage_colours(frame(1.2))
    assert teal > 100 and red < 10
    assert stage_colours(frame(1.9))[1] > 100

    # The pointer has run and the closing state is up, its tick in the accent.
    def change(a: float, b: float) -> float:
        return float(np.abs(frame(a) - frame(b)).mean())

    assert change(2.3, 4.0) > 0.3


def test_a_kinetic_word_is_built_letter_by_letter(tmp_path: Path) -> None:
    word = MotionElement(type="kinetic_word", start=0.5, end=2.3, text="SPOKÓJ",
                         reason="The key word.")  # fmt: skip
    plan = MotionPlan(rationale="Word.", accent_color="#28BCA5", elements=[word])
    frame, _ = _render(tmp_path, plan, seconds=2.5, brand_colours=["#28BCA5", "#D23150"])

    def teal(at: float) -> int:
        top = frame(at)[: HEIGHT // 4]
        return int((np.abs(top - [40, 188, 165]).sum(axis=-1) < 70).sum())

    assert teal(0.4) == 0
    # Letters keep arriving, then the whole word holds.
    assert 0 < teal(0.6) < teal(1.4)
    assert teal(2.0) == pytest.approx(teal(1.6), rel=0.1)


def test_an_inset_card_shows_a_picture_and_a_trimmed_clip(tmp_path: Path) -> None:
    picture = tmp_path / "strona.png"
    Image.new("RGB", (1600, 900), (40, 188, 165)).save(picture)
    clip = tmp_path / "rolka.mp4"
    # Red for its first second, blue after: the card must open on blue.
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=c=red:s=320x180:r=30:d=1",
         "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=2",
         "-filter_complex", "[0][1]concat=n=2:v=1", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )  # fmt: skip
    plan = MotionPlan(
        rationale="Insets.",
        elements=[
            MotionElement(type="inset", start=0.3, end=1.9, image_asset=str(picture),
                          rights="own picture", reason="The page."),
            MotionElement(type="inset", start=2.0, end=3.8, video_asset=str(clip),
                          source_start=1.2, source_end=2.8, position="center",
                          rights="own reel", reason="The earlier reel."),
        ],
    )  # fmt: skip
    margins = {"top": 10, "right": 6, "bottom": 22, "left": 6}
    frame, _ = _render(tmp_path, plan, seconds=4.0, safe_margins=margins)

    page = frame(1.2)
    teal = np.abs(page - [40, 188, 165]).sum(axis=-1) < 60
    rows, cols = np.flatnonzero(teal.any(axis=1)), np.flatnonzero(teal.any(axis=0))
    # 70 % of the width, at the picture's own 16:9, just under the top margin.
    assert (cols.max() - cols.min()) / WIDTH == pytest.approx(0.7, abs=0.03)
    assert rows.min() / HEIGHT == pytest.approx(0.1, abs=0.02)
    card_height = 0.7 * WIDTH / (16 / 9) / HEIGHT
    assert (rows.max() - rows.min()) / HEIGHT == pytest.approx(card_height, abs=0.02)
    middle = frame(3.0)[HEIGHT // 2 - 5 : HEIGHT // 2 + 5, WIDTH // 2 - 5 : WIDTH // 2 + 5]
    assert middle[..., 2].mean() > 150 and middle[..., 0].mean() < 80  # blue: trimmed in


def test_a_custom_component_is_drawn_in_its_zone_and_a_failing_one_left_out(
    tmp_path: Path,
) -> None:
    from social_video.motion.custom import TEMPLATE, component_path
    from social_video.pipeline import stage_render
    from social_video.schemas.base import load_artifact
    from social_video.schemas.edl import EDL, EDLRange
    from social_video.schemas.qa import RenderManifest
    from social_video.schemas.workflow import RemotionLicenseAttestation, Renderer
    from social_video.sources import build_manifest
    from social_video.workspace.layout import Workspace

    source = _black(tmp_path, 3.0)
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    opening = "<AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', "
    block = TEMPLATE.replace(
        opening + "fontFamily: brand.font}}>", "<AbsoluteFill style={{background: brand.accent}}>"
    )
    for name, text in (("block", block), ("bad", TEMPLATE + "\nconst u = 'https://x.y/z';\n")):
        path = component_path(ws.root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    plan = MotionPlan(
        rationale="Custom.", accent_color="#D23150",
        elements=[
            MotionElement(type="custom", start=0.5, end=2.5, component="block", reason="r"),
            MotionElement(type="custom", start=0.5, end=2.5, component="bad", position="center",
                          reason="r"),
        ],
    )  # fmt: skip
    manifest = build_manifest([source])
    edl = EDL(output_width=WIDTH, output_height=HEIGHT, output_fps="30/1", normalize_audio=False,
              ranges=[EDLRange(source=manifest.ids[0], start=0, end=3)])  # fmt: skip
    output = tmp_path / "final.mp4"
    stage_render(
        edl, manifest, ws, quality="preview", output=output, renderer=Renderer.REMOTION,
        motion_plan=plan,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )  # fmt: skip

    evidence = load_artifact(RenderManifest, ws.renders / "final.manifest.json")
    assert [a["component"] for a in evidence.custom_applied] == ["block"]
    assert evidence.custom_rejected[0]["component"] == "bad"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.5", "-i", str(output),
                    "-frames:v", "1", str(tmp_path / "c.png")], check=True)  # fmt: skip
    with Image.open(tmp_path / "c.png") as image:
        pixels = np.asarray(image.convert("RGB")).astype(int)
    red = (pixels[..., 0] > 170) & (pixels[..., 1] < 90) & (pixels[..., 2] < 120)
    rows = np.flatnonzero(red.any(axis=1))
    # The good block fills its top zone and nothing else; the refused one,
    # in the centre zone, is not drawn.
    assert rows.min() / HEIGHT == pytest.approx(0.06 + 10 / 1920, abs=0.01)
    assert (rows.max() - rows.min()) / HEIGHT == pytest.approx(0.24, abs=0.01)
    assert not red[HEIGHT // 2].any()
