"""A picture slowed under a voice from another file: the voice keeps its pace."""

from __future__ import annotations

from pathlib import Path

import pytest

from social_video.edl.render import DRAFT, render_edl
from social_video.ffmpeg.probe import probe
from social_video.qa.av_sync import envelope, envelope_lag
from social_video.schemas.edl import EDL, EDLRange
from social_video.sources import build_manifest
from tests.conftest import ffmpeg, make_video, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def test_speed_retimes_the_picture_and_leaves_the_audio_source_alone(tmp_path: Path) -> None:
    picture = make_video(tmp_path / "plac.mp4", width=320, height=568, duration=2.0, audio=False)
    voice = tmp_path / "glos.m4a"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "aevalsrc='0.5*sin(2*PI*500*t)*lt(mod(t*3.7,1.3),0.3)':s=48000:d=3",
        "-c:a",
        "aac",
        str(voice),
    )
    manifest = build_manifest([picture, voice])
    edl = EDL(
        output_width=320,
        output_height=568,
        output_fps="30/1",
        normalize_audio=False,
        ranges=[
            EDLRange(
                source="plac",
                start=0.0,
                end=1.76,
                speed=0.8,
                audio_source="glos",
                audio_start=0.0,
                audio_end=2.2,
            )
        ],
    )
    assert edl.total_duration == pytest.approx(2.2)
    output = tmp_path / "out.mp4"
    render_edl(edl, manifest, output, quality=DRAFT)

    info = probe(output)
    assert info.duration == pytest.approx(2.2, abs=0.05)
    assert info.video is not None and info.video.nb_frames == 66
    # The voice is the voice: same pace and position as in its own file.
    reference = tmp_path / "voice-cut.wav"
    ffmpeg("-i", str(voice), "-t", "2.2", str(reference))
    assert envelope_lag(envelope(reference), envelope(output)) == pytest.approx(0.0, abs=0.01)
