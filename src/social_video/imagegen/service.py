"""Ask a cloud image model for one background plate.

Only text leaves the machine. No frame, transcript file, brand asset or media
path is ever uploaded: the caller passes a description, and the guardrail below
is prepended so the model returns a background rather than an attempt at
typography. Image models mangle diacritics and cannot honour a brand contract,
so every word on a finished cover or end card is drawn locally instead.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from functools import partial
from io import BytesIO
from typing import Any

from PIL import Image

from social_video.errors import ImageGenerationError, ValidationError
from social_video.imagegen.providers import ImageProvider
from social_video.schemas.visuals import ImageProviderName

#: Prepended to every prompt. Restated as a negative list because image models
#: comply with "no text" far more reliably when the ban is enumerated.
PLATE_GUARDRAIL = (
    "Create a background plate for a vertical social video. "
    "Absolute requirements: no text, no letters, no numbers, no words, no captions, "
    "no watermarks, no logos, no user-interface elements, and no human faces or "
    "recognisable people. Composition must stay calm and uncluttered in the centre "
    "so headline typography can be placed over it later. "
    "Subject and mood: "
)

#: A prompt longer than this is a sign the caller is pasting content, not describing one.
MAX_PROMPT_CHARS = 1200

Transport = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


def build_prompt(description: str) -> str:
    text = " ".join(description.split())
    if not text:
        raise ValidationError("an image prompt needs a description of the plate")
    if len(text) > MAX_PROMPT_CHARS:
        raise ValidationError(
            f"image prompt is {len(text)} characters; keep it under {MAX_PROMPT_CHARS}. "
            "Describe the plate, do not paste the transcript."
        )
    return PLATE_GUARDRAIL + text


def strip_guardrail(prompt: str) -> str:
    """Return the description behind a prompt, whether or not it is guarded.

    The agent is told to fetch the guarded prompt, pass it to its native tool
    verbatim, and hand it back when registering the result. Re-guarding a
    prompt that already carries the preamble would record it twice, and
    rejecting it would push the agent towards paraphrasing what it actually
    sent.
    """
    text = " ".join(prompt.split())
    preamble = " ".join(PLATE_GUARDRAIL.split())
    return text[len(preamble) :].strip() if text.startswith(preamble) else text


def generate_plate(
    provider: ImageProvider,
    description: str,
    *,
    width: int,
    height: int,
    transport: Transport | None = None,
    timeout: float = 180.0,
) -> tuple[bytes, str]:
    """Return PNG bytes for one plate, plus the exact prompt that produced it."""
    prompt = build_prompt(description)
    send = transport or partial(_post_json, timeout=timeout)
    if provider.name is ImageProviderName.OPENAI_API:
        payload, headers = _openai_request(provider, prompt, width=width, height=height)
    else:
        # The Gemini image endpoint decides its own output size, so the aspect
        # ratio is stated in words and the result is cropped locally.
        prompt = f"{prompt} Frame it for a {_aspect_words(width, height)} canvas."
        payload, headers = _gemini_request(provider, prompt)
    try:
        response = send(provider.endpoint, payload, headers)
    except ImageGenerationError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ImageGenerationError(
            f"could not reach the {provider.name.value} image API: {exc}"
        ) from exc
    encoded = (
        _openai_image(response)
        if provider.name is ImageProviderName.OPENAI_API
        else _gemini_image(response)
    )
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ImageGenerationError(
            f"{provider.name.value} returned image data that is not valid base64"
        ) from exc
    return _as_png(raw, provider.name), prompt


def _openai_request(
    provider: ImageProvider, prompt: str, *, width: int, height: int
) -> tuple[dict[str, Any], dict[str, str]]:
    payload = {
        "model": provider.model,
        "prompt": prompt,
        "n": 1,
        "size": _openai_size(width, height),
    }
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }
    return payload, headers


def _gemini_request(provider: ImageProvider, prompt: str) -> tuple[dict[str, Any], dict[str, str]]:
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"x-goog-api-key": provider.api_key, "Content-Type": "application/json"}
    return payload, headers


def _openai_size(width: int, height: int) -> str:
    """The Images API accepts three fixed shapes; pick the closest one."""
    ratio = width / height
    if ratio < 0.9:
        return "1024x1536"
    if ratio > 1.1:
        return "1536x1024"
    return "1024x1024"


def _aspect_words(width: int, height: int) -> str:
    ratio = width / height
    if ratio < 0.9:
        return "vertical 9:16"
    if ratio > 1.1:
        return "landscape 16:9"
    return "square 1:1"


def _openai_image(response: dict[str, Any]) -> str:
    data = response.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        encoded = data[0].get("b64_json")
        if isinstance(encoded, str) and encoded:
            return encoded
    raise ImageGenerationError(
        f"the OpenAI image response contained no image: {_summary(response)}"
    )


def _gemini_image(response: dict[str, Any]) -> str:
    candidates = response.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            parts = (candidate or {}).get("content", {}).get("parts", [])
            for part in parts if isinstance(parts, list) else []:
                inline = part.get("inlineData") or part.get("inline_data") or {}
                encoded = inline.get("data")
                if isinstance(encoded, str) and encoded:
                    return encoded
    raise ImageGenerationError(
        f"the Gemini image response contained no image: {_summary(response)}"
    )


def _summary(response: dict[str, Any]) -> str:
    """Surface the provider's own error text; it is the actionable part."""
    error = response.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    text = json.dumps(response, ensure_ascii=False)
    return text[:400] + ("..." if len(text) > 400 else "")


def _as_png(raw: bytes, provider: ImageProviderName) -> bytes:
    """Re-encode through Pillow so a malformed or non-image payload fails here."""
    try:
        image = Image.open(BytesIO(raw))
        image.load()
    except OSError as exc:
        raise ImageGenerationError(
            f"{provider.value} returned data that is not a readable image"
        ) from exc
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _post_json(
    url: str, payload: dict[str, Any], headers: dict[str, str], *, timeout: float = 180.0
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            parsed = {}
        message = _summary(parsed) if parsed else detail[:400]
        raise ImageGenerationError(
            f"image provider rejected the request (HTTP {exc.code}): {message}"
        ) from exc
    try:
        parsed_body = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ImageGenerationError("image provider returned a non-JSON response") from exc
    if not isinstance(parsed_body, dict):
        raise ImageGenerationError("image provider returned an unexpected JSON shape")
    return parsed_body
