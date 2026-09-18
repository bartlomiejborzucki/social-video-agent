---
name: social-video-agent
description: Create project-aware Reels and Shorts from recordings with local transcription, an explicit plan and EDL, persistent stages, rendering, and QA. Use when asked to edit, trim, caption, reframe, review or resume a preview, or create delivery variants. Do not use for generated video or simple conversion.
license: Apache-2.0
metadata:
  version: "0.5.0"
---

# Project-aware social video editing

Start from what the target project says about brand and editing style. Never
mistake this installed skill's directory for the user's project.

## Route the request

1. Resolve the **target project root** from an explicit path, otherwise the
   current directory or nearest Git root. Stay within it.
2. If the edit workspace contains `workflow-state.json`, read it and resume its
   `current_stage`; chat history is not state.
3. Otherwise, before discovery, ingest, probing, or transcription, explain that
   Remotion is the default motion-design renderer and obtain one explicit
   declaration: `free_license_eligible` or `company_license_confirmed`. If the
   user cannot make either declaration, stop the default workflow. Only a user
   who explicitly opts out may continue with `--renderer ffmpeg`. Read
   [workflow.md](references/workflow.md) for the exact boundary.
4. Then read [project-context.md](references/project-context.md) and run Stage 0
   discovery as part of Stage 1:

   ```bash
   social-video-agent workflow init INPUT --project-root PROJECT \
     --remotion-license DECLARATION --language USER_LANGUAGE
   ```

   If project config exists, run `social-video-agent config validate PROJECT
   --workspace WORKSPACE`. Treat `brand-contract.json` as executable input and
   stop on a missing required asset or component-version mismatch.

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
- On Windows use Linux tools inside WSL2 and centralized path normalization;
  never use `ffmpeg.exe` or a PowerShell/WSL bridge.
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
- Generated imagery is optional and credential-gated. Run `image status` before
  offering a cover or end-card plate: a ChatGPT or Gemini plan is not API access,
  and Claude has no image API at all. A plate is a background only; the image
  model never draws text, and consent is a project policy or an explicit flag.
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

After project rules and user overrides, default to restraint: meaning, clarity,
natural rhythm, clean cuts, audio, framing, captions, then effects. Technical
success is not editorial approval: Stage 3 must inspect the opening sheet, hook,
story, cut boundaries, final ten seconds, dense final-five-second sheet, last
frame, and motion/audio ending, then always write valid `qa-editorial.json`.
