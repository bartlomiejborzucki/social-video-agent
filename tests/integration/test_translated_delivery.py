"""1.6 on a real render: a delivery variant with translated captions burned in."""

from __future__ import annotations

from pathlib import Path

import pytest

from social_video.captions.ass import write_ass
from social_video.captions.srt import write_vtt
from social_video.captions.translate import (
    apply_translation,
    export_for_translation,
    translated_paths,
)
from social_video.delivery import deliver_workspace, validate_delivery_manifest
from social_video.errors import ValidationError
from social_video.ffmpeg.probe import probe
from social_video.schemas.base import save_artifact
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.edl import EDL, EDLRange
from social_video.sources import build_manifest
from social_video.workspace.layout import Workspace
from tests.conftest import make_video, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]
W, H = 540, 960


def test_a_language_variant_is_rendered_and_delivered_with_its_sidecars(tmp_path: Path) -> None:
    source = make_video(tmp_path / "talk.mp4", width=W, height=H, duration=4.0)
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    save_artifact(build_manifest([source]), ws.source_manifest)
    style = CaptionStyle()
    track = CaptionTrack(
        language="pl",
        cues=[
            CaptionCue(index=1, start=0.2, end=1.6, text="Trzy błędy"),
            CaptionCue(index=2, start=1.8, end=3.2, text="Po pierwsze napisy"),
        ],
    )
    save_artifact(track, ws.captions / "main.json")
    ass = write_ass(track, style, ws.captions / "main.ass", width=W, height=H)
    save_artifact(
        EDL(output_width=W, output_height=H, output_fps="30", captions=str(ass),
            ranges=[EDLRange(source="talk", start=0, end=3.5)]),
        ws.edl,
    )  # fmt: skip
    data = export_for_translation(track, "en", style)
    data["cues"][0]["translation"] = "Three mistakes"
    data["cues"][1]["translation"] = "First, captions"
    english = apply_translation(track, data, style, language="en")
    paths = translated_paths(ws.captions, "main", "en")
    destination = tmp_path / "out"

    with pytest.raises(ValidationError, match="no en captions"):
        deliver_workspace(
            ws, destination, with_captions=False, no_captions=False, srt=False, vtt=False,
            poster=False, languages=["en"], allow_temporary=True,
        )  # fmt: skip

    save_artifact(english, paths["json"])
    write_vtt(english, paths["vtt"])
    write_ass(english, style, paths["ass"], width=W, height=H)
    manifest = deliver_workspace(
        ws, destination, with_captions=False, no_captions=False, srt=True, vtt=False,
        poster=False, languages=["en"], allow_temporary=True,
    )  # fmt: skip

    delivered = {Path(item.path).name for item in manifest.items}
    assert {"final-en.mp4", "captions.en.srt", "captions.srt"} <= delivered
    assert probe(destination / "final-en.mp4").video.display_size == (W, H)
    assert "First, captions" in (destination / "captions.en.srt").read_text(encoding="utf-8")
    validate_delivery_manifest(manifest)
