"""Which image API *this CLI* can reach, and what it cannot see at all.

There are four ways imagery can be made, and only two of them are visible from
a Python process:

* a **native image tool** the host hands to the agent (ChatGPT, Codex). It
  needs no API key of the user's own, it cannot be called from a script,
  subprocess or Node, and nothing in this module can detect it. Only the agent
  knows whether the tool is in its own tool list this session.
* **Canva**, over an MCP connection that belongs to the agent for the same
  reason.
* **OpenAI's image API**, with ``OPENAI_API_KEY``.
* **Gemini's image API**, with ``GEMINI_API_KEY`` or ``GOOGLE_API_KEY``.

This module answers only the last two, and says so. The previous version
answered "no image generation is possible" when no key was present, which is
false on a host whose agent has a native image tool -- and it justified that
answer with a claim about subscriptions. Absence of a credential is evidence
about this CLI, not about the session.

Availability is never inferred from a subscription or a host name. The host is
used only to choose between two keys that are both present, and to write a
diagnostic the user can act on.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from social_video.schemas.visuals import CapabilityState, ImageProviderName

#: Cheapest current model per provider that still renders a usable plate.
DEFAULT_MODELS = {
    ImageProviderName.OPENAI_API: "gpt-image-1-mini",
    ImageProviderName.GEMINI_API: "gemini-2.5-flash-image",
}

COST_NOTES = {
    ImageProviderName.OPENAI_API: (
        "billed per image on the API key, separately from any ChatGPT plan"
    ),
    ImageProviderName.GEMINI_API: "AI Studio free tier applies until its daily quota is spent",
}

#: Accepted spellings of SOCIAL_VIDEO_IMAGE_PROVIDER from before the rename.
_PROVIDER_ALIASES = {"openai": "openai_api", "gemini": "gemini_api"}

#: Only these two can be driven from here. The native tool is the agent's.
_CREDENTIALS: dict[ImageProviderName, tuple[str, ...]] = {
    ImageProviderName.OPENAI_API: ("OPENAI_API_KEY",),
    ImageProviderName.GEMINI_API: ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}

_ENDPOINTS = {
    ImageProviderName.OPENAI_API: "https://api.openai.com/v1/images/generations",
    ImageProviderName.GEMINI_API: (
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
_FALLBACK_ORDER = (ImageProviderName.GEMINI_API, ImageProviderName.OPENAI_API)

#: Host preference when more than one key is present.
_HOST_PREFERENCE = {
    "codex": ImageProviderName.OPENAI_API,
    "gemini_cli": ImageProviderName.GEMINI_API,
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


#: What this CLI is able to check. Stated in every status so an absent key is
#: never read as "image generation is impossible in this session".
CHECKED_SCOPE = "local_api_integrations_only"

#: What only the agent can establish, because these are its own tools.
AGENT_MUST_DETERMINE = ("native_imagegen", "canva")


@dataclass(frozen=True)
class ImageProviderStatus:
    """Whether *this CLI* can generate a plate, and what it did not check.

    ``available`` is deliberately narrow: it means this CLI holds a usable API
    credential and can draw a plate itself. It says nothing about the agent's
    native image tool, which this process cannot see.
    """

    available: bool
    host: str
    reason: str
    provider: ImageProvider | None = None
    candidates: tuple[str, ...] = ()

    @property
    def cli_can_generate(self) -> bool:
        return self.available

    def to_dict(self) -> dict[str, object]:
        return {
            "cli_can_generate": self.available,
            # Kept for callers written against the old shape; same meaning as
            # cli_can_generate, and explicitly not a session-wide verdict.
            "available": self.available,
            "checked": CHECKED_SCOPE,
            "native_imagegen": CapabilityState.UNKNOWN_TO_CLI.value,
            "canva": CapabilityState.UNKNOWN_TO_CLI.value,
            "agent_must_determine": list(AGENT_MUST_DETERMINE),
            "host": self.host,
            "reason": self.reason,
            "provider": self.provider.name.value if self.provider else None,
            "model": self.provider.model if self.provider else None,
            "credential_env": self.provider.credential_env if self.provider else None,
            "cost_note": self.provider.cost_note if self.provider else "",
            "credentials_found": list(self.candidates),
            "openai_api": _state(ImageProviderName.OPENAI_API, self.candidates).value,
            "gemini_api": _state(ImageProviderName.GEMINI_API, self.candidates).value,
        }


def _state(name: ImageProviderName, candidates: tuple[str, ...]) -> CapabilityState:
    wanted = set(_CREDENTIALS.get(name, ()))
    return CapabilityState.AVAILABLE if wanted & set(candidates) else CapabilityState.UNAVAILABLE


def local_api_capabilities(
    env: Mapping[str, str] | None = None,
) -> dict[str, CapabilityState]:
    """The two capabilities a Python process can honestly report on."""
    status = detect_image_provider(env)
    return {
        "openai_api": _state(ImageProviderName.OPENAI_API, status.candidates),
        "gemini_api": _state(ImageProviderName.GEMINI_API, status.candidates),
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
    # The short spellings predate the native tool and keep working.
    requested = _PROVIDER_ALIASES.get(requested, requested)
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
            chosen = None  # type: ignore[assignment]
        if chosen not in _CREDENTIALS:
            supported = ", ".join(item.value for item in _CREDENTIALS)
            reason = (
                f"SOCIAL_VIDEO_IMAGE_PROVIDER={requested!r} is not an API this CLI can "
                f"call (expected one of: {supported}, none)"
            )
            if chosen is ImageProviderName.CHATGPT_NATIVE:
                reason = (
                    "SOCIAL_VIDEO_IMAGE_PROVIDER cannot select chatgpt_native: the native "
                    "image tool belongs to the agent, which calls it itself and registers "
                    "the result with `image register`. This variable only chooses between "
                    f"the API integrations this CLI can call ({supported}, none)."
                )
            return ImageProviderStatus(
                available=False, host=host, reason=reason, candidates=candidates
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


#: Appended to every "no credential" reason. The CLI must never present its own
#: blindness as a session-wide verdict: on a host whose agent has a native
#: image tool, generation is available without any key of the user's own.
NATIVE_CAVEAT = (
    "Only local API integrations were checked. A native image tool provided to the "
    "agent by its host is not visible from this process and is not ruled out: if the "
    "agent has one, it should call it directly and register the file with "
    "`image register`."
)


def _no_credentials_reason(host: str) -> str:
    keys = "GEMINI_API_KEY (AI Studio free tier) or OPENAI_API_KEY (billed per image)"
    if host == "claude":
        detail = (
            "no image API credential is set, and Anthropic's API has no image-generation "
            f"endpoint this CLI can call. Set {keys} to let the CLI draw plates itself."
        )
    elif host == "codex":
        detail = (
            "no image API credential is set, so this CLI cannot call an image API itself. "
            f"Set {keys} to let it, or let the agent use its own image tool."
        )
    elif host == "gemini_cli":
        detail = (
            "no image API credential is set. Set GEMINI_API_KEY from AI Studio to let the "
            "CLI draw plates itself on its free tier."
        )
    else:
        detail = f"no image API credential is set. Set {keys} to let the CLI draw plates."
    return f"{detail} {NATIVE_CAVEAT}"
