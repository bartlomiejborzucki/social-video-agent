"""Brand profiles: presentation settings, kept out of the editing engine.

Nothing here influences *what* gets cut. These are the knobs that decide how
the result looks, so a user's house style is reusable across projects and the
engine stays free of hard-coded taste.

Upstream freezes caption style into constants (two-word chunks, uppercase,
Helvetica, fixed margin) while its SKILL.md invites the agent to design caption
styles freely -- so the only way to restyle is to edit the renderer, which the
same document forbids.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from social_video.schemas.base import Artifact


class CaptionPosition(str, Enum):
    BOTTOM = "bottom"
    CENTER = "center"
    TOP = "top"
    LOWER_THIRD = "lower_third"


class CaptionCase(str, Enum):
    AS_SPOKEN = "as_spoken"
    UPPER = "upper"
    LOWER = "lower"


class CaptionStyle(Artifact):
    """How captions look and how they are chunked."""

    font_family: str = Field(
        default="",
        description="Empty means 'discover a Unicode-capable font on this machine'.",
    )
    font_size_pct: float = Field(
        default=5.0,
        gt=0.0,
        le=30.0,
        description="Percentage of output height, so the size is resolution independent. "
        "Upstream hard-codes a point size against libass's 288-line virtual "
        "canvas, which silently means something different at 1080p and 4K.",
    )
    bold: bool = True
    primary_colour: str = Field(default="#FFFFFF")
    outline_colour: str = Field(default="#000000")
    outline_width: float = Field(default=3.0, ge=0.0)
    shadow: float = Field(default=0.0, ge=0.0)
    background_box: bool = False

    position: CaptionPosition = CaptionPosition.BOTTOM
    #: Distance from the frame edge as a percentage of output height.
    #: The default clears the platform UI: on Reels and Shorts the bottom
    #: ~12% is covered by the caption/handle/actions overlay.
    margin_pct: float = Field(default=12.0, ge=0.0, le=45.0)

    case: CaptionCase = CaptionCase.AS_SPOKEN
    max_words_per_cue: int = Field(default=4, ge=1, le=20)
    max_chars_per_cue: int = Field(default=32, ge=8, le=120)
    min_cue_duration: float = Field(default=0.6, gt=0.0)
    highlight_active_word: bool = False
    highlight_colour: str = "#FFD400"
    speaker_colours: dict[str, str] = Field(default_factory=dict)


class BrandProfile(Artifact):
    """A reusable house style."""

    name: str = "default"
    description: str = ""

    captions: CaptionStyle = Field(default_factory=CaptionStyle)

    accent_colour: str = "#FFD400"
    background_colour: str = "#000000"
    title_font_family: str = ""
    logo_path: str | None = None

    #: Fraction of the frame kept clear of graphics at each edge.
    safe_margin_pct: float = Field(default=6.0, ge=0.0, le=25.0)

    #: 0 = no movement at all, 1 = as much as the profile allows.
    motion_intensity: float = Field(default=0.25, ge=0.0, le=1.0)
    punch_in_max: float = Field(
        default=1.12,
        ge=1.0,
        le=1.5,
        description="Largest punch-in scale. Punch-ins mark editorial moments; "
        "constant zooming is not a style, it is a tell.",
    )
    transition_default: str = "cut"
    broll_density: float = Field(default=0.0, ge=0.0, le=1.0)
    music_enabled: bool = False
    sfx_enabled: bool = False


class OutputProfile(Artifact):
    """An output format plus its editorial defaults.

    Profiles are configuration. Adding one must never mean adding code.
    """

    name: str
    description: str = ""
    width: int = Field(default=1080, gt=0)
    height: int = Field(default=1920, gt=0)
    target_duration: float | None = Field(default=None, gt=0.0)
    duration_range: tuple[float, float] | None = None

    #: Editorial posture. Restraint is the default everywhere.
    remove_filler: bool = True
    remove_false_starts: bool = True
    #: Pauses longer than this may be tightened; shorter ones are speech rhythm.
    max_pause: float = Field(default=0.9, gt=0.0)
    #: Never tighten a pause below this. Removing every pause sounds robotic.
    min_pause: float = Field(default=0.18, ge=0.0)
    #: Padding kept either side of a cut so words are not clipped.
    cut_padding: float = Field(default=0.08, ge=0.0)

    captions_enabled: bool = True
    punch_ins_enabled: bool = False
    default_reframe: str = "fit"
