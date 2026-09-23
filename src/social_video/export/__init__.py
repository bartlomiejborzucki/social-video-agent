"""Hand the cut to a human editor: the EDL as an NLE timeline.

``edl.json`` stays canonical. These formats carry the cuts -- which source, from
where to where, placed where -- so an editor can open the edit in Premiere,
DaVinci Resolve, Final Cut Pro or any OpenTimelineIO tool and continue by hand.
Everything the formats cannot express (crops, captions, graphics, music, voice
cleanup) is listed in the export's notes rather than silently dropped.
"""

from social_video.export.timeline import (
    FORMATS,
    ExportTimeline,
    build_export_timeline,
    write_export,
)

__all__ = ["FORMATS", "ExportTimeline", "build_export_timeline", "write_export"]
