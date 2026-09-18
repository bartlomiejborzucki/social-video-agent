"""Publishing metadata: the text that ships beside the video.

The agent writes this; the CLI only validates it and carries it into the
delivery manifest. Titles and hashtags are editorial decisions, so generating
them in code would be inventing content the user never approved.
"""

from __future__ import annotations

import re

from pydantic import Field, field_validator

from social_video.schemas.base import Artifact

_HASHTAG = re.compile(r"^#?[0-9A-Za-z_\u00C0-\u024F\u0370-\u04FF]{2,60}$")


class PublishMetadata(Artifact):
    """One platform's caption copy for one finished video."""

    platform: str = Field(min_length=1, max_length=40)
    language: str = Field(min_length=2, max_length=16)
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=2200)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    #: Accessibility text describing the frame, not repeating the title.
    alt_text: str = Field(default="", max_length=1000)
    #: The spoken sentence the video opens on, quoted from the transcript.
    spoken_hook: str | None = Field(default=None, max_length=300)
    cta: str | None = Field(default=None, max_length=200)

    @field_validator("hashtags")
    @classmethod
    def _normalise_hashtags(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        normalised: list[str] = []
        for tag in values:
            if not _HASHTAG.match(tag):
                raise ValueError(
                    f"hashtag {tag!r} must be a single word, optionally prefixed with '#'"
                )
            value = tag if tag.startswith("#") else f"#{tag}"
            key = value.casefold()
            if key in seen:
                raise ValueError(f"duplicate hashtag {value!r}")
            seen.add(key)
            normalised.append(value)
        return normalised
