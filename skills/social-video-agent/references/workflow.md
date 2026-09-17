# Persistent editing workflow

`workflow-state.json` is the cross-model and cross-conversation router. Read it
before doing work. After completing a stage run `workflow complete N`; this
validates artifacts and advances state. `workflow status` reports missing files,
the next stage, model tier/name, effort, and continuation prompt.

## Stage 0 + Stage 1 — discovery and editorial plan

Recommended tier: `editorial_strong`.

Discover context first. Inspect/probe media, create or reuse local transcripts,
and read the packed transcript end-to-end. Determine the strongest hook,
standalone story, false starts, repetitions, meaningful pauses, ordering,
ending, B-roll/punch-in opportunities, and caption behavior. Project defaults
apply only after discovery; the current request wins and overrides are recorded.

Produce `context/*`, `edit-plan.json` (including `style_sources` and
`user_overrides`), and optionally `edit-plan.md`. Do not render. Validate, mark
Stage 1 complete, and stop in guided mode.

## Stage 2 — technical execution and preview

Recommended tier: `execution_balanced`.

Read state, project context, and approved plan. Do not rediscover unchanged
context or reinterpret the story without a concrete execution conflict. Create
the exact `edl.json`, captions, 9:16 framing, restrained requested graphics,
and `preview.mp4`; run technical QA and write `qa/qa-technical.json`. Stop and
hand off for editorial review.

## Stage 3 — supervising-editor review

Recommended tier: `editorial_strong`.

Read context, plan, EDL, and technical QA. Inspect the preview efficiently:
first 1–3 seconds, relevant cut boundaries, key transitions, final ten seconds,
dense final-five-second sheet, last frame, and audio/motion ending. Judge hook,
standalone clarity, story, pacing, speech, captions, hierarchy, brand fit, and
whether every proposed change is justified.

Always write exactly one validated `qa-editorial.json` contract:

```json
{"status":"approved","fixes":[]}
```

or concrete `changes_requested` fixes. Do not render final video.

## Stage 4 — corrections and finalization

Recommended tier: `execution_balanced`.

Apply only `qa-editorial.json` fixes. Approval is a no-op; do not perform a new
full editorial analysis. Update affected EDL/captions/visual plan, render a new
preview if substantive, rerun technical QA, render `final.mp4`, fully decode it,
and verify duration, CFR, A/V timing, captions, ending, and destination. Persist
state.

## Stage 5 — optional delivery

Recommended tier: `mechanical_fast`.

Create only approved mechanical variants: no-captions, resolution variants,
SRT/VTT, thumbnail/poster, names, and `delivery-manifest.json`. Hash or compare
the EDL before and after; Stage 5 must not change cuts or story.

## Resume and failure behavior

Each edit has its own workspace and state. On a new conversation locate the
workspace, run status, report the active stage and missing artifacts, then
continue. Malformed/unknown schemas stop with an actionable error. Never infer
completion from chat history or from a file's mere presence without validation.
