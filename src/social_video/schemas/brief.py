"""A montage brief from the monthly package, parsed into what the edit uses.

The brief is written per reel: how it was recorded, a scenario of rows (time,
shot, what is said, the text on screen), montage notes and the cover text.
It overrides project defaults for that one edit: its first line is the first
caption, its short on-screen labels are text over the shot, and its cover
text only ever becomes `cover.jpg`.
"""

from __future__ import annotations

from pydantic import Field

from social_video.schemas.base import Artifact


class BriefRow(Artifact):
    """One row of the scenario: | Czas | Ujęcie | Co mówisz | Napis na ekranie |."""

    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    shot: str = ""
    said: str = ""
    #: The on-screen text, split where the brief separates lines with " / ".
    on_screen: list[str] = Field(default_factory=list)
    #: The line is said by a child off screen. A child's voice is never
    #: synthesised: without it in the recording, the line is text only.
    child_off_screen: bool = False


class BriefLabel(Artifact):
    """A short text over the shot, in the top safe zone, never its own card."""

    text: str = Field(min_length=1, max_length=48)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)


class Brief(Artifact):
    title: str = ""
    source: str = ""
    recording: str = ""
    rows: list[BriefRow] = Field(default_factory=list)
    montage: str = ""
    cover_title: str = ""
    cover_subtitle: str = ""
    #: The text the first caption must carry, from the first row.
    first_cue_text: str = ""
    #: The first line is a child's, off screen: text only unless recorded.
    first_line_is_child: bool = False
    labels: list[BriefLabel] = Field(default_factory=list)
