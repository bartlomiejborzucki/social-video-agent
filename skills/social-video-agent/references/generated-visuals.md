# Cover, end card, and generated plates

A short is judged twice: once by its cover in a grid of other covers, and once
by its first second. This is the cover half, plus the optional end card.

## What the image model is allowed to draw

Only a **background plate**: no text, no letters, no logos, no faces. Every word
on a finished cover or end card is drawn locally from `brand-contract.json`.
Image models mangle Polish diacritics and cannot honour a brand contract, so a
model-rendered headline is off-brand by construction.

A real frame of the speaker over a brand gradient beats a generated background
for anything person-led. Reach for a plate when the frame genuinely has nothing
to show: a screen recording, a voice-over, a privacy-stopped visual.

## Detect first, promise second

```bash
social-video-agent image status --json
```

`available` is decided by credentials, not by which assistant is running:

| Host | What is actually available |
|---|---|
| Codex / ChatGPT | A ChatGPT plan is not API access. Needs `OPENAI_API_KEY`, billed per image. |
| Gemini CLI | No built-in image tool. `GEMINI_API_KEY` from AI Studio has a free tier. |
| Claude | Anthropic has no image API. Plates are unavailable; say so and move on. |

When it is unavailable, do not offer to generate anything. Compose the cover from
a real frame and keep the end card typographic — that path is always available
and needs no network.

`SOCIAL_VIDEO_IMAGE_PROVIDER=openai|gemini|none` and `SOCIAL_VIDEO_IMAGE_MODEL`
override the choice.

## Consent

Generating a plate sends prompt text off the machine. Media, transcripts and
brand assets never leave, and there is no upload of any file.

- Project opt-in: `image_generation_policy: optional` in the project config.
- One-off: `--allow-cloud-image`.
- Neither: the command refuses. Absence of a policy is not consent.

The basis is recorded in `visuals.json` with the provider, model, exact prompt
and SHA-256.

## Commands

```bash
social-video-agent image plate WORKSPACE --kind cover_plate \
  --prompt "ciemne studio, miękkie boczne światło, głęboka zieleń" --allow-cloud-image

social-video-agent cover WORKSPACE --title "Nikt ci tego nie powie" \
  --subtitle "Trzy błędy w montażu"

social-video-agent deliver WORKSPACE --output DEST --with-captions --cover --publish
```

`cover` uses, in order: an explicit `--plate`, the recorded `cover_plate`, then a
frame from the finished video. Write the title as editorial copy: it is the same
promise the first spoken line makes, not a description of the file.

## End-card plate

An `end_card` element in `motion-plan.json` may carry `image_asset` pointing at a
local PNG/JPEG/WebP, with `image_dim_pct` controlling how far it is darkened
behind the text. Only `end_card` accepts one: a plate behind a hook or callout
covers the person the edit exists for.

```json
{
  "type": "end_card",
  "start": 27.5,
  "end": 30.0,
  "text": "Cała metoda w opisie",
  "reason": "Domknięcie po puencie, bez obiecywania czegoś spoza materiału.",
  "image_asset": "/abs/edit/assets/generated/end_card_plate.png",
  "image_dim_pct": 55
}
```

## Canva

Canva's remote MCP server (`https://mcp.canva.com/mcp`, configured in the
repository's `.mcp.json`) is a reasonable source of a **brand-template cover** or
an exported end-card graphic when the project already lives in Canva. It is not
a source of B-roll: generic stock footage that does not match the recording
reads as filler. When the server is not connected, this route simply does not
exist — never describe a design as created when no tool call made it.
