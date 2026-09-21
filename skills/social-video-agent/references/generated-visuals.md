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

## Four sources, and the CLI can only see two

| Source | Who calls it | Needs a key of the user's own |
|---|---|---|
| Native image tool (ChatGPT/Codex `ImageGen`) | **you, the agent** | no |
| Canva, over MCP | **you, the agent** | no |
| OpenAI image API | this CLI | `OPENAI_API_KEY` |
| Gemini image API | this CLI | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |

A native image tool and an MCP connection are *your* tools. No Python, Node or
subprocess can call them, so `image status` cannot see them either:

```bash
social-video-agent image status --json
```

It reports `cli_can_generate`, plus `checked: local_api_integrations_only` and
`native_imagegen: unknown_to_cli`. **An absent API key is not evidence that
imagery is unavailable this session.** Never tell a user that image generation
is impossible because a key is missing, and never say Codex has no image tool:
look at your own tool list instead. Equally, never assume the tool exists
because of a subscription — the only truth is whether it is callable now.

`SOCIAL_VIDEO_IMAGE_PROVIDER=openai_api|gemini_api|none` (the old `openai` and
`gemini` still work) and `SOCIAL_VIDEO_IMAGE_MODEL` override the CLI's choice.
The variable cannot select the native tool, because the CLI cannot call it.

## Order of preference

Work down this list, and stop at the first source that genuinely serves the
edit. Availability is not a reason: do not reach for Canva or an image model
because they are there.

1. the user's own material, or a real frame of their video;
2. Canva, when the connection exists *and* a company template is called for;
3. the native image tool;
4. OpenAI or Gemini API, when a key is present;
5. a locally composed background, gradient or frame.

## Using the native tool

```bash
# 1. take the guarded prompt, so the no-text rule reaches your tool verbatim
social-video-agent image prompt --prompt "calm night-sky gradient"

# 2. call your own image tool with exactly that prompt, and save the file
#    somewhere outside a cloud-synced folder

# 3. register it, with the prompt you actually sent
social-video-agent image register WORKSPACE --file /tmp/plate.png \
  --kind end_card_plate --prompt "<the guarded prompt>" \
  --purpose "background behind the end card"
```

`image register` copies the pixels into the workspace, hashes the result and
records the provenance. It does not pretend the CLI generated anything: the
record names `chatgpt_native` and `native_imagegen`, and leaves `model` empty
unless your tool actually reported one. Do not invent a model name.

`image plate` remains the route when the CLI holds an API key and can draw the
plate itself.

## Recording what this session can do

```bash
social-video-agent image capabilities WORKSPACE \
  --native-imagegen available --canva unavailable \
  --chosen-source chatgpt_native \
  --reason "The end card needs an abstract background; no frame of this screen
            recording works, and there is no company template for it."
```

This writes `visual-capabilities.json`: what you observed about your own tools,
what the CLI checked about API keys, the project's policy, the source you chose
and why. The CLI refuses a record that contradicts itself — a source whose
capability is unavailable, a cloud source under `image_generation_policy: none`,
or an API key marked `unknown_to_cli` when it is plainly checkable.

Re-check the session-dependent halves when you resume: a native tool and an MCP
connection belong to the session that had them, not to the project.

## Consent

Generating a plate sends prompt text off the machine. Media, transcripts and
brand assets never leave, and there is no upload of any file.

- Project opt-in: `image_generation_policy: optional` in the project config.
- One-off: `--allow-cloud-image`.
- The user asked for this specific image, in so many words: `--user-request`.
  It covers that image and does not extend to the next one.
- Neither: the command refuses. Absence of a policy is not consent.

The native tool needs the same consent as an API. A host-provided tool is still
a cloud service and the prompt still leaves the machine. And
`image_generation_policy: none` outranks every one-off: with that policy set,
nothing is generated or registered, by the CLI or by you.

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
