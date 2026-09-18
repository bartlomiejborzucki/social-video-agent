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
) -> list[str]:
    if style is None or captions is None:
        return []
    applied = ["burned_in"]
    if highlight:
        applied.append(ACTIVE_WORD_HIGHLIGHT)
    elif style.highlight_active_word:
        applied.append(ACTIVE_WORD_UNAVAILABLE)
    if style.background_style.value != "none":
        applied.append(f"background_{style.background_style.value}")
    if style.bold:
        applied.append("bold")
    return applied
