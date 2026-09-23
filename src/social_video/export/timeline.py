"""One frame-exact timeline model, and the four formats written from it.

Record positions use the renderer's own frame allocation, so a cut lands on
the same frame in the NLE as in the rendered file. Source positions are frames
at the timeline rate from the start of each file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

from social_video.edl.render import allocate_range_frames
from social_video.ffmpeg.probe import probe, resolve_output_fps
from social_video.fsutil import atomic_write_bytes
from social_video.schemas.edl import EDL, ReframeMode
from social_video.schemas.source import SourceManifest

FORMATS = ("fcpxml", "xmeml", "otio", "edl")
_SUFFIX = {"fcpxml": ".fcpxml", "xmeml": ".xml", "otio": ".otio", "edl": ".edl"}


@dataclass(frozen=True)
class Media:
    id: str
    path: Path
    frames: int
    width: int
    height: int
    has_audio: bool

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class Clip:
    media: Media
    source_in: int
    record_in: int
    length: int
    note: str = ""


@dataclass
class ExportTimeline:
    name: str
    fps: Fraction
    width: int
    height: int
    video: list[Clip] = field(default_factory=list)
    audio: list[Clip] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def frames(self) -> int:
        return max((c.record_in + c.length for c in self.video), default=0)

    @property
    def media(self) -> list[Media]:
        seen: dict[str, Media] = {}
        for clip in [*self.video, *self.audio]:
            seen.setdefault(clip.media.id, clip.media)
        return list(seen.values())


def build_export_timeline(edl: EDL, manifest: SourceManifest) -> ExportTimeline:
    """Place every range on video and audio tracks, and note what cannot travel."""
    infos = {entry.id: probe(entry.resolved_path()) for entry in manifest.sources}
    video_infos = [infos[r.effective_video_source] for r in edl.ranges]
    fps = Fraction(resolve_output_fps(video_infos, edl.output_fps))
    frame_counts = allocate_range_frames(edl, str(fps))

    def media(source_id: str) -> Media:
        entry = manifest.by_id(source_id)
        info = infos[source_id]
        width, height = info.video.display_size if info.video else (0, 0)
        return Media(
            id=source_id,
            path=entry.resolved_path().resolve(),
            frames=max(1, round(info.duration * fps)),
            width=width,
            height=height,
            has_audio=info.has_audio,
        )

    timeline = ExportTimeline(
        name=edl.name, fps=fps, width=edl.output_width, height=edl.output_height
    )
    record = 0
    for index, (rng, length) in enumerate(zip(edl.ranges, frame_counts, strict=True)):
        where = f"range {index + 1}"
        timeline.video.append(
            Clip(
                media=media(rng.effective_video_source),
                source_in=round(rng.effective_video_start * fps),
                record_in=record,
                length=length,
                note=rng.reason,
            )
        )
        audio = media(rng.effective_audio_source)
        if audio.has_audio:
            timeline.audio.append(
                Clip(
                    media=audio,
                    source_in=round(rng.effective_audio_start * fps),
                    record_in=record,
                    length=length,
                    note=rng.reason,
                )
            )
        record += length
        mode = rng.reframe.mode if rng.reframe else edl.default_reframe
        if mode is not ReframeMode.FIT:
            timeline.notes.append(f"{where}: {mode.value} framing is not exported; reframe it")
        if rng.zoom > 1.0:
            timeline.notes.append(f"{where}: punch-in to {rng.zoom:g} is not exported")
        if rng.speed != 1.0:
            timeline.notes.append(
                f"{where}: speed {rng.speed:g} is not exported; the clip plays at normal speed "
                "for the same length"
            )
        if (
            rng.visual_fill_strategy is not None
            or rng.freeze_at is not None
            or rng.hold_last_frame_until is not None
        ):
            timeline.notes.append(f"{where}: held or filled picture is not exported")
    if edl.captions:
        timeline.notes.append(f"captions are not in the timeline; import {edl.captions}")
    if edl.overlays:
        timeline.notes.append(f"{len(edl.overlays)} overlay(s) are not exported")
    if edl.audio_bed is not None:
        timeline.notes.append(f"the music bed {edl.audio_bed.path} is not exported")
    if edl.sound_effects:
        timeline.notes.append(f"{len(edl.sound_effects)} sound effect(s) are not exported")
    timeline.notes.append(
        "voice cleanup, loudness normalisation and motion graphics exist only in the render"
    )
    return timeline


def write_export(timeline: ExportTimeline, fmt: str, directory: Path) -> Path:
    if fmt not in FORMATS:
        raise ValueError(f"unknown export format {fmt!r}; expected one of {', '.join(FORMATS)}")
    writer = {"fcpxml": fcpxml, "xmeml": xmeml, "otio": otio_json, "edl": cmx3600}[fmt]
    target = directory / f"{timeline.name}{_SUFFIX[fmt]}"
    atomic_write_bytes(target, writer(timeline).encode("utf-8"))
    return target


# -- CMX 3600 -------------------------------------------------------------


def _timecode(frame: int, fps: Fraction) -> str:
    """Non-drop-frame timecode at the nominal integer rate."""
    base = round(fps)
    seconds, frames = divmod(frame, base)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def cmx3600(timeline: ExportTimeline) -> str:
    """The lowest common denominator every NLE reads; clips relink by name."""
    lines = [f"TITLE: {timeline.name}", "FCM: NON-DROP FRAME", ""]
    event = 0
    for kind, clips in (("V", timeline.video), ("AA", timeline.audio)):
        for clip in clips:
            event += 1
            lines.append(
                f"{event:03d}  AX       {kind:<5} C        "
                f"{_timecode(clip.source_in, timeline.fps)} "
                f"{_timecode(clip.source_in + clip.length, timeline.fps)} "
                f"{_timecode(clip.record_in, timeline.fps)} "
                f"{_timecode(clip.record_in + clip.length, timeline.fps)}"
            )
            lines.append(f"* FROM CLIP NAME: {clip.media.name}")
            if clip.note:
                lines.append(f"* COMMENT: {' '.join(clip.note.split())[:200]}")
            lines.append("")
    return "\n".join(lines)


# -- OpenTimelineIO ---------------------------------------------------------


def _rational(value: int, fps: Fraction) -> dict:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": float(fps), "value": float(value)}


def _range(start: int, length: int, fps: Fraction) -> dict:
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "start_time": _rational(start, fps),
        "duration": _rational(length, fps),
    }


def otio_json(timeline: ExportTimeline) -> str:
    fps = timeline.fps

    def track(kind: str, clips: list[Clip]) -> dict:
        children: list[dict] = []
        cursor = 0
        for clip in clips:
            if clip.record_in > cursor:
                children.append(
                    {
                        "OTIO_SCHEMA": "Gap.1",
                        "name": "",
                        "metadata": {},
                        "source_range": _range(0, clip.record_in - cursor, fps),
                        "effects": [],
                        "markers": [],
                        "enabled": True,
                    }
                )
            children.append(
                {
                    "OTIO_SCHEMA": "Clip.2",
                    "name": clip.media.name,
                    "metadata": {"social_video": {"reason": clip.note}},
                    "source_range": _range(clip.source_in, clip.length, fps),
                    "effects": [],
                    "markers": [],
                    "enabled": True,
                    "media_references": {
                        "DEFAULT_MEDIA": {
                            "OTIO_SCHEMA": "ExternalReference.1",
                            "name": clip.media.name,
                            "metadata": {},
                            "available_range": _range(0, clip.media.frames, fps),
                            "available_image_bounds": None,
                            "target_url": clip.media.path.as_uri(),
                        }
                    },
                    "active_media_reference_key": "DEFAULT_MEDIA",
                }
            )
            cursor = clip.record_in + clip.length
        return {
            "OTIO_SCHEMA": "Track.1",
            "name": f"{kind} 1",
            "metadata": {},
            "source_range": None,
            "effects": [],
            "markers": [],
            "enabled": True,
            "children": children,
            "kind": kind,
        }

    document: dict[str, object] = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": timeline.name,
        "metadata": {
            "social_video": {
                "width": timeline.width,
                "height": timeline.height,
                "notes": timeline.notes,
            }
        },
        "global_start_time": None,
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "metadata": {},
            "source_range": None,
            "effects": [],
            "markers": [],
            "enabled": True,
            "children": [track("Video", timeline.video), track("Audio", timeline.audio)],
        },
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


# -- Final Cut Pro X (FCPXML 1.8) ------------------------------------------


def _seconds(frames: int, fps: Fraction) -> str:
    value = Fraction(frames) / fps
    return f"{value.numerator}/{value.denominator}s" if value.denominator != 1 else f"{value}s"


def fcpxml(timeline: ExportTimeline) -> str:
    fps = timeline.fps
    frame = Fraction(1) / fps
    # 1.8: the newest version whose asset carries its own ``src``. Final Cut,
    # Resolve and OpenTimelineIO all read it; 1.9's media-rep is not universal.
    root = ET.Element("fcpxml", version="1.8")
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        id="r0",
        name="social-video-agent",
        frameDuration=f"{frame.numerator}/{frame.denominator}s",
        width=str(timeline.width),
        height=str(timeline.height),
    )
    ids: dict[str, str] = {}
    for number, media in enumerate(timeline.media, start=1):
        ids[media.id] = f"r{number}"
        ET.SubElement(
            resources,
            "asset",
            id=f"r{number}",
            name=media.name,
            start="0s",
            duration=_seconds(media.frames, fps),
            hasVideo="1" if media.width else "0",
            hasAudio="1" if media.has_audio else "0",
            src=media.path.as_uri(),
        )
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="social-video-agent")
    project = ET.SubElement(event, "project", name=timeline.name)
    sequence = ET.SubElement(
        project,
        "sequence",
        format="r0",
        duration=_seconds(timeline.frames, fps),
        tcStart="0s",
        tcFormat="NDF",
    )
    spine = ET.SubElement(sequence, "spine")
    audio_by_record = {clip.record_in: clip for clip in timeline.audio}
    for clip in timeline.video:
        sound = audio_by_record.get(clip.record_in)
        split = sound is not None and sound.media.id != clip.media.id
        video = ET.SubElement(
            spine,
            "asset-clip",
            ref=ids[clip.media.id],
            name=clip.media.name,
            offset=_seconds(clip.record_in, fps),
            start=_seconds(clip.source_in, fps),
            duration=_seconds(clip.length, fps),
            format="r0",
            tcFormat="NDF",
        )
        if split or not clip.media.has_audio:
            video.set("srcEnable", "video")
        if split and sound is not None:
            # Sound recorded separately rides under its picture as a connected clip.
            ET.SubElement(
                video,
                "asset-clip",
                ref=ids[sound.media.id],
                name=sound.media.name,
                lane="-1",
                offset=_seconds(clip.source_in, fps),
                start=_seconds(sound.source_in, fps),
                duration=_seconds(sound.length, fps),
                srcEnable="audio",
            )
        if clip.note:
            ET.SubElement(video, "note").text = clip.note
    ET.indent(root)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
        + ET.tostring(root, encoding="unicode")
        + "\n"
    )


# -- Premiere / Final Cut 7 XML (xmeml 5) ----------------------------------


def _rate(parent: ET.Element, fps: Fraction) -> None:
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(round(fps))
    ET.SubElement(rate, "ntsc").text = "TRUE" if fps.denominator == 1001 else "FALSE"


def xmeml(timeline: ExportTimeline) -> str:
    fps = timeline.fps
    root = ET.Element("xmeml", version="5")
    sequence = ET.SubElement(root, "sequence", id="sequence-1")
    ET.SubElement(sequence, "name").text = timeline.name
    ET.SubElement(sequence, "duration").text = str(timeline.frames)
    _rate(sequence, fps)
    media_el = ET.SubElement(sequence, "media")
    video = ET.SubElement(media_el, "video")
    fmt = ET.SubElement(ET.SubElement(video, "format"), "samplecharacteristics")
    ET.SubElement(fmt, "width").text = str(timeline.width)
    ET.SubElement(fmt, "height").text = str(timeline.height)
    _rate(fmt, fps)
    written: set[str] = set()

    def file_element(parent: ET.Element, media: Media) -> None:
        element = ET.SubElement(parent, "file", id=f"file-{media.id}")
        if media.id in written:
            return
        written.add(media.id)
        ET.SubElement(element, "name").text = media.name
        ET.SubElement(element, "pathurl").text = media.path.as_uri()
        _rate(element, fps)
        ET.SubElement(element, "duration").text = str(media.frames)
        described = ET.SubElement(element, "media")
        if media.width:
            chars = ET.SubElement(ET.SubElement(described, "video"), "samplecharacteristics")
            ET.SubElement(chars, "width").text = str(media.width)
            ET.SubElement(chars, "height").text = str(media.height)
        if media.has_audio:
            ET.SubElement(ET.SubElement(described, "audio"), "channelcount").text = "2"

    def clip_items(track: ET.Element, clips: list[Clip], kind: str) -> None:
        for number, clip in enumerate(clips, start=1):
            item = ET.SubElement(track, "clipitem", id=f"{kind}-{number}")
            ET.SubElement(item, "name").text = clip.media.name
            ET.SubElement(item, "duration").text = str(clip.media.frames)
            _rate(item, fps)
            ET.SubElement(item, "start").text = str(clip.record_in)
            ET.SubElement(item, "end").text = str(clip.record_in + clip.length)
            ET.SubElement(item, "in").text = str(clip.source_in)
            ET.SubElement(item, "out").text = str(clip.source_in + clip.length)
            file_element(item, clip.media)
            if clip.note:
                comments = ET.SubElement(item, "comments")
                ET.SubElement(comments, "mastercomment1").text = clip.note

    clip_items(ET.SubElement(video, "track"), timeline.video, "video")
    audio = ET.SubElement(media_el, "audio")
    clip_items(ET.SubElement(audio, "track"), timeline.audio, "audio")
    ET.indent(root)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
        + ET.tostring(root, encoding="unicode")
        + "\n"
    )
