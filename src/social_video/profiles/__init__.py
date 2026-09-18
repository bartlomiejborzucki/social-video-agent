"""Output profiles and brand profiles, loaded from configuration.

Adding a profile must never mean adding code. Built-in profiles ship as JSON
next to this module; a user profile with the same name in the workspace or in
the app home overrides it.
"""

from social_video.profiles.registry import (
    available_brands,
    available_platforms,
    available_profiles,
    load_brand,
    load_platform,
    load_profile,
)

__all__ = [
    "available_brands",
    "available_platforms",
    "available_profiles",
    "load_brand",
    "load_platform",
    "load_profile",
]
