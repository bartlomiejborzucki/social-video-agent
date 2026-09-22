---
name: social-video-agent
description: Create project-aware Reels and Shorts from recordings with local transcription, an explicit plan and EDL, persistent stages, rendering, and QA. Use when asked to edit, trim, caption, reframe, review or resume a preview, or create delivery variants. Do not use for generated video or simple conversion.
license: Apache-2.0
metadata:
  version: "0.6.3"
  last_updated: "2026-09-22"
---

# Project-aware social video editing

Start from what the target project says about brand and editing style. Never
mistake this installed skill's directory for the user's project.

## Route the request

1. Resolve the **target project root** from an explicit path, otherwise the
   current directory or nearest Git root. Stay within it.
2. If the edit workspace contains `workflow-state.json`, read it and resume its
   `current_stage`; chat history is not state.
3. Otherwise, before discovery, ingest, probing, or transcription, check
   `social-video-agent remotion-license status --project-root PROJECT --json`.
   If it reports a usable declaration, say which one and continue. If not,
   explain that Remotion is the default motion-design renderer and ask for one
   explicit declaration: `free_license_eligible` or
   `company_license_confirmed`. Never decide eligibility, and never supply the
   acknowledgement yourself; record the user's own answer:

   ```bash
   social-video-agent remotion-license attest DECLARATION \
     --project-root PROJECT --accept-terms
   ```

   If the user cannot make either declaration, stop the default workflow. Only a
   user who explicitly opts out may continue with `--renderer ffmpeg`. Read
   [workflow.md](references/workflow.md) for the exact boundary.
4. Then read [project-context.md](references/project-context.md) and run Stage 0
   discovery as part of Stage 1:

   ```bash
   social-video-agent workflow init INPUT --project-root PROJECT \
     --language USER_LANGUAGE
   ```

   The project declaration is reused automatically. Pass
   `--remotion-license DECLARATION` only to declare for this one edit, which
   overrides the stored statement without replacing it.

   If project config exists, run `social-video-agent config validate PROJECT
   --workspace WORKSPACE`. Treat `brand-contract.json` as executable input and
   stop on a missing required asset or component-version mismatch. Captions are
   never shortened to fit: the contract's `font_size_pct`, `max_words_per_cue`
   and `max_chars_per_cue` decide the geometry, validation refuses a geometry
   whose text cannot be drawn, and a cue that still does not fit fails the
   render rather than losing its ending. Rebuild the caption track after
   changing any of those; cue length is part of the contract.

   Audio: `audio_cleanup_policy` defaults to `measured`, so the render repairs
   only what it measures as broken in that recording and reports every change.
   Always tell the user what was changed and that `--no-audio-cleanup` or
   `audio_cleanup_policy: none` renders the audio as recorded. Never describe
   it as enhancement, and never claim clipping can be repaired.

6. Read [workflow.md](references/workflow.md) plus only the active stage's
   relevant reference below. Use [model-routing.md](references/model-routing.md)
   for handoffs.
7. In guided mode validate and save artifacts, stop at the boundary, recommend
   the next model, and give the exact continuation prompt in the user's
   language. The skill cannot switch models.

Use `social-video-agent workflow status WORKSPACE --json` for “Where are we?”
and resume requests.

## Modes and invariants

Default `guided` route uses the OpenAI or Claude recommendation returned by
workflow status for every active stage, including Stages 4 and 5. OpenAI's
route is Sol → Terra → Sol → Terra → Luna; Claude alternatives are
defined in the same central mapping. Astra and its Claude counterpart are
exceptional escalation only. “Use this model for everything” or
“Just make it quickly” selects `continuous` but keeps every artifact and check.
Budgets are `economical`, `balanced`, and `quality`; the single executable
tier/name mapping is `src/social_video/workflow/model-routing.json`.

- Discover context before defaults. User instructions win; record overrides
  and source-linked facts, not hidden reasoning or invented guidance.
- Source media is immutable. Keep discovery local and bounded. Never upload
  media/brand files without explicit cloud configuration.
- Reason over `takes-packed.md`; never invent timestamps or improvised FFmpeg
  command strings.
- Media tools are always the Linux ones inside WSL2, with centralized path
  normalization. Never `ffmpeg.exe`, Windows Python or Windows Node, and never
  mix Windows and Linux binaries in one render. Two runtime modes are
  supported: in `wsl-native` the agent is already inside WSL, so there is no
  boundary and no bridge; in `windows-agent-wsl-runtime` the agent is a native
  Windows process and delegates every editing operation through the one
  supported adapter, `scripts/windows/social-video-agent.ps1` — never an
  improvised `wsl.exe` command string. `runtime_mode: auto` detects which,
  from the real platform rather than from a terminal preference. Read
  [hybrid-runtime.md](references/hybrid-runtime.md) only when the agent is on
  Windows.
- Never hide missing privacy-safe footage with an automatic long freeze, loop,
  zoom, transition, or synthetic motion.
- For every Remotion workflow, Stage 2 writes `motion-plan.json`. Use discovered
  project typography/colors and only story-serving hook, lower-third, callout,
  or end-card elements. Remotion enriches an approved edit; it does not decide
  the story or repair insufficient footage.
- Stage 2 compiles project config into `brand-contract.json`; render only a
  matching EDL/contract. Stage 4 requires technical QA and `qa/qa-brand.json`.
- Music and effects are licence-gated and policy-gated: `audio_bed` and every
  sound effect require `license_confirmed`, the project's `music_policy` and
  `sfx_policy` decide whether they may exist at all, and nothing is ever placed
  on a timer. Never source, clear, or describe a track's licence for the user.
- `speaker` framing correlates mouth movement with the speech envelope. When no
  face is convincingly the talker it falls back to prominence and records that
  in the reframe reason; do not describe the result as speaker detection when it
  declined to pick.
- Generated imagery has four possible sources and you can see two that the CLI
  cannot. Prefer the user's own material or a real frame; then Canva when a
  company template is genuinely called for; then your host's native image tool;
  then an image API with a key; then a locally composed background. Availability
  is not a reason to use something.
- `image status` reports only the API integrations the CLI can reach. It cannot
  see your native image tool or an MCP connection, so a missing `OPENAI_API_KEY`
  never means imagery is impossible — check your own tool list. Never claim your
  host has no image tool, and never assume it has one because of a subscription.
- Your native tool is yours to call: take the guarded prompt from
  `image prompt`, pass it verbatim, save the file outside any cloud-synced
  folder, then `image register` it. Record no model name unless the tool gives
  one. Consent still applies, because the prompt still leaves the machine, and
  `image_generation_policy: none` outranks every one-off.
- A plate is a background only. Captions, headlines, CTAs and logos are rendered
  locally by Remotion, so never ask an image tool for Polish text in a graphic.
- Stage 5 uses `social-video-agent deliver`; preserve the EDL hash and verify
  every delivery-manifest entry.

## References

| Need | Read |
|---|---|
| Discovery, precedence, cache | [project-context.md](references/project-context.md) |
| Stage contracts and resume | [workflow.md](references/workflow.md) |
| Model tiers and handoff copy | [model-routing.md](references/model-routing.md) |
| Artifact fields and endings | [artifacts.md](references/artifacts.md) |
| Captions, framing, brand style | [style.md](references/style.md) |
| Music, ducking, sound effects | [audio.md](references/audio.md) |
| Cover, end card, generated plates | [generated-visuals.md](references/generated-visuals.md) |
| Platform safe zones and publish copy | [publishing.md](references/publishing.md) |
| Several clips from long video | [shorts.md](references/shorts.md) |
| Setup/render failures | [troubleshooting.md](references/troubleshooting.md) |
| Agent on Windows, engine in WSL2 | [hybrid-runtime.md](references/hybrid-runtime.md) |

After project rules and user overrides, default to restraint: meaning, clarity,
natural rhythm, clean cuts, audio, framing, captions, then effects. Technical
success is not editorial approval: Stage 3 must inspect the opening sheet, hook,
story, cut boundaries, final ten seconds, dense final-five-second sheet, last
frame, and motion/audio ending, then always write valid `qa-editorial.json`.
