"""Cloud image generation for cover and end-card plates.

Detection is credential-based, consent is explicit, and every plate keeps its
provider, model, prompt and hash. The image model never draws text.
"""

from social_video.imagegen.plates import generate_workspace_plate, resolve_consent
from social_video.imagegen.providers import (
    ImageProvider,
    ImageProviderStatus,
    detect_host,
    detect_image_provider,
)
from social_video.imagegen.service import PLATE_GUARDRAIL, build_prompt, generate_plate

__all__ = [
    "PLATE_GUARDRAIL",
    "ImageProvider",
    "ImageProviderStatus",
    "build_prompt",
    "detect_host",
    "detect_image_provider",
    "generate_plate",
    "generate_workspace_plate",
    "resolve_consent",
]
