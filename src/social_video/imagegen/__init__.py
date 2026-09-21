"""Image generation for cover and end-card plates.

Four possible sources, and this package is honest about which of them it can
see. It can call OpenAI's or Gemini's image API when a credential is present.
It cannot see the native image tool a host gives its agent, or an MCP
connection to Canva -- those belong to the agent, which calls them itself and
registers the result here. An absent API key is therefore never evidence that
imagery cannot be made this session.

Consent is explicit whichever source is used, because every one of them sends
a prompt to somebody else's service. Every plate keeps its provider, tool,
prompt, consent basis and hash. No image tool ever draws text: every word in
the finished video is rendered locally from the brand contract.
"""

from social_video.imagegen.capabilities import (
    CLOUD_SOURCES,
    LOCAL_SOURCES,
    SOURCE_PRIORITY,
    load_capabilities,
    record_capabilities,
)
from social_video.imagegen.plates import (
    generate_workspace_plate,
    register_visual,
    resolve_consent,
)
from social_video.imagegen.providers import (
    AGENT_MUST_DETERMINE,
    CHECKED_SCOPE,
    ImageProvider,
    ImageProviderStatus,
    detect_host,
    detect_image_provider,
    local_api_capabilities,
)
from social_video.imagegen.service import (
    PLATE_GUARDRAIL,
    build_prompt,
    generate_plate,
    strip_guardrail,
)

__all__ = [
    "AGENT_MUST_DETERMINE",
    "CHECKED_SCOPE",
    "CLOUD_SOURCES",
    "LOCAL_SOURCES",
    "PLATE_GUARDRAIL",
    "SOURCE_PRIORITY",
    "ImageProvider",
    "ImageProviderStatus",
    "build_prompt",
    "detect_host",
    "detect_image_provider",
    "generate_plate",
    "generate_workspace_plate",
    "load_capabilities",
    "local_api_capabilities",
    "record_capabilities",
    "register_visual",
    "resolve_consent",
    "strip_guardrail",
]
