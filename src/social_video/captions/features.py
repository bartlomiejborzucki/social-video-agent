"""What a renderer actually drew, as opposed to what the contract asked for.

Brand QA used to compare the compiled contract against a copy of itself, so a
feature the compositor silently dropped still passed. These names are recorded
by whichever renderer ran, and QA checks them against the contract.
"""

from __future__ import annotations

from social_video.schemas.brand import CaptionStyle
from social_video.schemas.captions import CaptionTrack

#: Recorded when the contract asks for a per-word highlight and it was drawn.
ACTIVE_WORD_HIGHLIGHT = "active_word_highlight"
#: Recorded when it was asked for and the caption data could not support it.
ACTIVE_WORD_UNAVAILABLE = "active_word_highlight_unavailable"
#: Recorded when the contract lists brand keywords and the renderer coloured them.
KEYWORD_EMPHASIS = "keyword_emphasis"
#: Recorded when the motion plan's timed punch-ins were drawn.
PUNCH_IN = "punch_in"
#: Recorded when the motion plan's transitions were drawn.
TRANSITIONS = "transitions"
#: Recorded when the spoken word was animated as the contract asks (pop, box).
CAPTION_ANIMATION = "caption_animation"
#: Recorded when an animation was asked for and this renderer cannot draw it.
CAPTION_ANIMATION_UNAVAILABLE = "caption_animation_unavailable"
#: Recorded when caption lines were wrapped against the real font's metrics.
CAPTION_LAYOUT_MEASURED = "caption_layout_measured"
#: Recorded when the font could not be measured and a conservative estimate of
#: glyph width was used instead. Captions are still never truncated; they are
#: just laid out with less precision, so QA reports it.
CAPTION_LAYOUT_ESTIMATED = "caption_layout_estimated"


def highlight_possible(style: CaptionStyle | None, captions: CaptionTrack | None) -> bool:
    """A per-word highlight needs per-word timings, not just the setting."""
    return bool(
        style
        and style.highlight_active_word
        and captions
        and any(cue.words for cue in captions.cues)
    )


def caption_features(
    style: CaptionStyle | None,
    captions: CaptionTrack | None,
    *,
    highlight: bool,
    animated: bool = False,
) -> list[str]:
    """What was drawn. ``animated`` says whether this renderer can move words."""
    if style is None or captions is None:
        return []
    applied = ["burned_in"]
    if highlight and style.animation not in ("", "none"):
        applied.append(CAPTION_ANIMATION if animated else CAPTION_ANIMATION_UNAVAILABLE)
    if highlight:
        applied.append(ACTIVE_WORD_HIGHLIGHT)
    elif style.highlight_active_word:
        applied.append(ACTIVE_WORD_UNAVAILABLE)
    if style.emphasis_words:
        applied.append(KEYWORD_EMPHASIS)
    if style.background_style.value != "none":
        applied.append(f"background_{style.background_style.value}")
    if style.bold:
        applied.append("bold")
    return applied
