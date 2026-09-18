"""Which image model, if any, this host can actually reach.

Detection is credential-based on purpose. A ChatGPT or Gemini subscription is
not API access: the ChatGPT app draws images, the API does not come with it, and
neither Codex CLI nor Gemini CLI exposes an image tool. The only honest signal
is whether a usable key is present. The host is a hint used to pick between two
available keys and to write a diagnostic the user can act on.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from social_video.schemas.visuals import ImageProviderName

#: Cheapest current model per provider that still renders a usable plate.
DEFAULT_MODELS = {
    ImageProviderName.OPENAI: "gpt-image-1-mini",
    ImageProviderName.GEMINI: "gemini-2.5-flash-image",
}

COST_NOTES = {
    ImageProviderName.OPENAI: "billed per image on the API key, separately from any ChatGPT plan",
    ImageProviderName.GEMINI: "AI Studio free tier applies until its daily quota is spent",
}

_CREDENTIALS: dict[ImageProviderName, tuple[str, ...]] = {
    ImageProviderName.OPENAI: ("OPENAI_API_KEY",),
    ImageProviderName.GEMINI: ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}

_ENDPOINTS = {
    ImageProviderName.OPENAI: "https://api.openai.com/v1/images/generations",
    ImageProviderName.GEMINI: (
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    ),
}

#: Host markers, checked in order. The first match wins.
_HOSTS = (
    ("claude", ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ANTHROPIC_API_KEY")),
    ("codex", ("CODEX_SANDBOX", "CODEX_HOME", "CODEX_CLI_VERSION")),
    ("gemini_cli", ("GEMINI_CLI", "GEMINI_SANDBOX", "GEMINI_CODE_ASSIST")),
)

#: Used when no host preference applies. Gemini first: its free tier is the
#: only one of the two that can cost nothing.
_FALLBACK_ORDER = (ImageProviderName.GEMINI, ImageProviderName.OPENAI)

#: Host preference when more than one key is present.
_HOST_PREFERENCE = {
    "codex": ImageProviderName.OPENAI,
    "gemini_cli": ImageProviderName.GEMINI,
}


@dataclass(frozen=True)
class ImageProvider:
    name: ImageProviderName
    model: str
    endpoint: str
    credential_env: str
    api_key: str

    @property
    def cost_note(self) -> str:
        return COST_NOTES[self.name]


@dataclass(frozen=True)
class ImageProviderStatus:
    """What the agent needs to decide between generating a plate and not."""

    available: bool
    host: str
    reason: str
    provider: ImageProvider | None = None
    candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "host": self.host,
            "reason": self.reason,
            "provider": self.provider.name.value if self.provider else None,
            "model": self.provider.model if self.provider else None,
            "credential_env": self.provider.credential_env if self.provider else None,
            "cost_note": self.provider.cost_note if self.provider else "",
            "credentials_found": list(self.candidates),
        }


def detect_host(env: Mapping[str, str] | None = None) -> str:
    environment = os.environ if env is None else env
    for host, markers in _HOSTS:
        if any(environment.get(marker) for marker in markers):
            return host
    return "unknown"


def detect_image_provider(env: Mapping[str, str] | None = None) -> ImageProviderStatus:
    """Resolve the image provider without contacting anything."""
    environment = os.environ if env is None else env
    host = detect_host(environment)
    found: dict[ImageProviderName, tuple[str, str]] = {}
    for name, variables in _CREDENTIALS.items():
        for variable in variables:
            value = environment.get(variable)
            if value and value.strip():
                found[name] = (variable, value.strip())
                break
    candidates = tuple(variable for variable, _ in found.values())

    requested = (environment.get("SOCIAL_VIDEO_IMAGE_PROVIDER") or "").strip().casefold()
    if requested in {"none", "off", "disabled"}:
        return ImageProviderStatus(
            available=False,
            host=host,
            reason="image generation is disabled by SOCIAL_VIDEO_IMAGE_PROVIDER",
            candidates=candidates,
        )
    if requested:
        try:
            chosen = ImageProviderName(requested)
        except ValueError:
            supported = ", ".join(item.value for item in ImageProviderName)
            return ImageProviderStatus(
                available=False,
                host=host,
                reason=(
                    f"SOCIAL_VIDEO_IMAGE_PROVIDER={requested!r} is not supported "
                    f"(expected one of: {supported}, none)"
                ),
                candidates=candidates,
            )
        if chosen not in found:
            expected = " or ".join(_CREDENTIALS[chosen])
            return ImageProviderStatus(
                available=False,
                host=host,
                reason=f"{chosen.value} was requested but {expected} is not set",
                candidates=candidates,
            )
    elif not found:
        return ImageProviderStatus(
            available=False, host=host, reason=_no_credentials_reason(host), candidates=candidates
        )
    else:
        preferred = _HOST_PREFERENCE.get(host)
        chosen = (
            preferred
            if preferred in found
            else next(name for name in _FALLBACK_ORDER if name in found)
        )

    variable, key = found[chosen]
    model = (environment.get("SOCIAL_VIDEO_IMAGE_MODEL") or "").strip() or DEFAULT_MODELS[chosen]
    provider = ImageProvider(
        name=chosen,
        model=model,
        endpoint=_ENDPOINTS[chosen].format(model=model),
        credential_env=variable,
        api_key=key,
    )
    return ImageProviderStatus(
        available=True,
        host=host,
        reason=f"{chosen.value} reachable with {model} via {variable}",
        provider=provider,
        candidates=candidates,
    )


def _no_credentials_reason(host: str) -> str:
    keys = "GEMINI_API_KEY (AI Studio free tier) or OPENAI_API_KEY (billed per image)"
    if host == "claude":
        return (
            "this host is Claude, and Anthropic exposes no image-generation API. "
            "Use the typographic end card and a frame-based cover, or set "
            f"{keys} to enable generated plates."
        )
    if host == "codex":
        return (
            "a ChatGPT plan does not include API image generation and Codex CLI has no "
            f"image tool. Set {keys} to enable generated plates."
        )
    if host == "gemini_cli":
        return (
            "Gemini CLI has no built-in image tool. Set GEMINI_API_KEY from AI Studio "
            "to enable generated plates on its free tier."
        )
    return f"no image credentials found. Set {keys} to enable generated plates."
