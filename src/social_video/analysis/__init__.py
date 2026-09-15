"""Signal analysis that informs, but does not make, editorial decisions."""

from social_video.analysis.scenes import detect_scenes
from social_video.analysis.silence import Pause, find_pauses

__all__ = ["Pause", "detect_scenes", "find_pauses"]
