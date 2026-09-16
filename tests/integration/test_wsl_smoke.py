"""Fast offline acceptance path for Linux and WSL media tooling."""

from __future__ import annotations

import hashlib

import pytest

from social_video.captions.ass import write_ass
from social_video.edl.render import DRAFT, render_edl
from social_video.ffmpeg.fonts import default_caption_font
from social_video.ffmpeg.probe import probe
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.edl import EDL, EDLRange
from social_video.sources import build_manifest
from tests.conftest import make_video, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


@pytest.mark.parametrize(
    ("width", "height", "fps"),
    [(640, 360, 30), (360, 640, 60)],
)
def test_offline_edit_with_unicode_caption_and_filename(tmp_path, width, height, fps):
    source = make_video(
        tmp_path / "Mój film testowy 01 ąćęłńóśźż.mp4",
        width=width,
        height=height,
        fps=fps,
        duration=1.2,
    )
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = build_manifest([source])
    source_id = manifest.ids[0]
    track = CaptionTrack(
        language="pl",
        cues=[CaptionCue(index=1, start=0.05, end=0.9, text="Zażółć gęślą jaźń")],
    )
    font = default_caption_font()
    subtitle = write_ass(
        track,
        CaptionStyle(),
        tmp_path / "Polskie napisy ąćęłńóśźż.ass",
        width=360,
        height=640,
        font_name=font.family if font else None,
    )
    edl = EDL(
        output_width=360,
        output_height=640,
        output_fps=f"{fps}/1",
        ranges=[EDLRange(source=source_id, start=0.0, end=1.0)],
    )
    output = tmp_path / "gotowy film ąćęłńóśźż.mp4"
    render_edl(edl, manifest, output, quality=DRAFT, caption_file=subtitle)

    rendered = probe(output)
    assert rendered.video.is_portrait
    assert rendered.video.fps_float == pytest.approx(float(fps), abs=0.5)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
