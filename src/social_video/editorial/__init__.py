"""Editorial machinery: where cuts land, and what is worth cutting."""

from social_video.editorial.boundaries import snap_range, snap_ranges
from social_video.editorial.draft import draft_edit_plan

__all__ = ["draft_edit_plan", "snap_range", "snap_ranges"]
