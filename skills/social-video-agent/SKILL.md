---
name: social-video-agent
description: Create project-aware Reels and Shorts from recordings with local transcription, an explicit plan and EDL, persistent stages, rendering, and QA. Use when asked to edit, trim, caption, reframe, review or resume a preview, or create delivery variants. Do not use for generated video or simple conversion.
license: Apache-2.0
metadata:
  version: "0.2.0"
---

# Project-aware social video editing

Start from what the target project says about brand and editing style. Never
mistake this installed skill's directory for the user's project.

## Route the request

1. Resolve the **target project root** from an explicit path, otherwise the
   current directory or nearest Git root. Stay within it.
2. If the edit workspace contains `workflow-state.json`, read it and resume its
   `current_stage`; chat history is not state.
3. Otherwise read [project-context.md](references/project-context.md) and run
   Stage 0 discovery as part of Stage 1:

   ```bash
   social-video-agent workflow init INPUT --project-root PROJECT --language USER_LANGUAGE
   ```

4. Read [workflow.md](references/workflow.md) plus only the active stage's
   relevant reference below. Use [model-routing.md](references/model-routing.md)
   for handoffs.
5. In guided mode validate and save artifacts, stop at the boundary, recommend
   the next model, and give the exact continuation prompt in the user's
   language. The skill cannot switch models.

Use `social-video-agent workflow status WORKSPACE --json` for “Where are we?”
and resume requests.

## Modes and invariants

Default `guided` route: Sol → Terra → Sol → Terra; Luna is optional delivery,
and Astra is exceptional escalation only. “Use this model for everything” or
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

## References

| Need | Read |
|---|---|
| Discovery, precedence, cache | [project-context.md](references/project-context.md) |
| Stage contracts and resume | [workflow.md](references/workflow.md) |
| Model tiers and handoff copy | [model-routing.md](references/model-routing.md) |
| Artifact fields and endings | [artifacts.md](references/artifacts.md) |
| Captions, framing, brand style | [style.md](references/style.md) |
| Several clips from long video | [shorts.md](references/shorts.md) |
| Setup/render failures | [troubleshooting.md](references/troubleshooting.md) |

After project rules and user overrides, default to restraint: meaning, clarity,
natural rhythm, clean cuts, audio, framing, captions, then effects. Technical
success is not editorial approval: Stage 3 must inspect the hook, story, cut
boundaries, final ten seconds, dense final-five-second sheet, last frame, and
motion/audio ending, then always write valid `qa-editorial.json`.
