# Persistent editing workflow

`workflow-state.json` is the cross-model and cross-conversation router. Read it
before doing work. After completing a stage run `workflow complete N`; this
validates artifacts and advances state. `workflow status` reports missing files,
the next stage, model tier/name, effort, and continuation prompt.

## Stage 0 — mandatory renderer and license gate

New workflows use Remotion by default. Before reading project context or media,
check whether the project already declared:

```bash
social-video-agent remotion-license status --project-root PROJECT --json
```

`usable: true` means the statement stands; report which declaration it is and
continue. Otherwise tell the user that Remotion's current license permits free
use for eligible users (including individuals, qualifying small organisations,
nonprofits, and non-commercial evaluation) and otherwise requires a Company
License. Ask for a declaration; do not decide eligibility for them and do not
describe this as legal advice.

- `free_license_eligible`: record it and continue.
- `company_license_confirmed`: record it and continue.
- neither: stop. Do not scan, transcribe, plan, or render.
- explicit user opt-out: initialize with `--renderer ffmpeg`; the core editor
  remains available without Remotion, but this is not the default route.

Record the user's own answer for the project, so later edits and later sessions
do not ask again:

```bash
social-video-agent remotion-license attest DECLARATION \
  --project-root PROJECT --accept-terms
```

`--accept-terms` states that a person read the terms and is declaring for
themselves. Ask first and use the answer given; never supply it on the user's
behalf. Use `--remotion-license DECLARATION` on `workflow init` only for a
one-edit declaration, which overrides the stored one without replacing it.

`remotion-license refresh` re-confirms the stored statement when the CLI asks
again (changed terms URL, a new release line, or a declaration older than a
year). `remotion-license revoke` withdraws it and stops new Remotion edits.
`workflow-state.json` records `remotion_license_source`, so the trail shows
whether an edit used the flag or the project declaration.

Current terms: <https://www.remotion.dev/license>. Never claim that installing
the npm package itself grants a license.

## Stage 0 + Stage 1 — discovery and editorial plan

Recommended tier: `editorial_strong`.

If the user gives a URL rather than a file, ask what right they have to edit the
material before anything else, then run `social-video-agent fetch URL --rights
"<their words>"`; never fill the statement in for them, and never fetch
someone else's video for re-upload. The file and its `.provenance.json` land in
`sources/`, and the file is then an ordinary immutable source.

Discover context first. Inspect/probe media, create or reuse local transcripts,
and read the packed transcript end-to-end. Determine the strongest hook,
standalone story, false starts, repetitions, meaningful pauses, ordering,
ending, B-roll/punch-in opportunities, and caption behavior. Project defaults
apply only after discovery; the current request wins and overrides are recorded.

Run `config validate` when project config is present. It creates executable
`brand-contract.json`; missing required font/logo assets or mixed
CLI/skill/plugin versions block the workflow before editorial work.

`social-video-agent cuts find SOURCE -w WORKSPACE` lists hesitations, doubled
words, restarted phrases and long pauses, each with an id, a confidence and the
quoted words. It changes nothing. Read every candidate against the transcript:
`high` is almost always a stumble; `medium` is often how the person talks, so
listen before accepting. Accept only what you agree with, by id
(`cuts accept -w WORKSPACE cut-003 cut-007`) or by kind
(`--kind pause --confidence high`); each becomes a drop in `edit-plan.json`
with its reason, and is removed exactly even inside a kept span.

Produce `context/*`, `edit-plan.json` (including `style_sources` and
`user_overrides`), and optionally `edit-plan.md`. Do not render. Validate, mark
Stage 1 complete, and stop in guided mode.

A workspace still on the FFmpeg renderer (created before Remotion was the
default, or with `--renderer ffmpeg`) switches with `social-video-agent workflow
renderer remotion -w WORKSPACE`, after the same licence declaration as Stage 0.
Past Stage 2 this reopens Stage 2, because the preview must be rendered again.

## Stage 2 — technical execution and preview

Recommended tier: `execution_balanced`.

Read state, project context, and approved plan. Do not rediscover unchanged
context or reinterpret the story without a concrete execution conflict. Create
the exact `edl.json`, captions, and 9:16 framing. `social-video-agent compile
SOURCE -w WORKSPACE` builds a word-aligned `edl.json` from the plan, accepted
cuts included; it refuses to overwrite an existing EDL without `--force`. For the default renderer also
write `motion-plan.json`: run `motion suggest`, accept the accents that serve
the story, add the graphics it cannot see, and keep the rhythm the project's
`motion_energy` asks for (see motion-design.md). Every graphic keeps its
reason. FFmpeg first creates the frame-accurate base edit;
Remotion composites the approved motion layer; then FFmpeg/ffprobe QA the final
`preview.mp4`. Write `qa/qa-technical.json`, stop, and hand off for editorial
review.

When the contract asks for an active-word highlight, the caption track must
carry word timings: the renderer records the features it actually drew and brand
QA fails if a contracted one was dropped.

Generate captions from the compiled brand contract. The EDL stores its
fingerprint, never an unresolvable project/profile name. Rounded caption boxes are drawn by
both renderers from the same measured layout; on the FFmpeg route libass draws
them with the brand font loaded from the project, so a project that cannot use
Remotion keeps its caption contract.

## Stage 3 — supervising-editor review

Recommended tier: `editorial_strong`.

For a Remotion render, `social-video-agent motion sheet -w WORKSPACE` writes
`qa/motion-sheet.png`: one labelled frame per graphic, punch-in and transition.
Check each lands on its words, stays readable, and covers no face or caption.

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
Current recommendations: OpenAI Sol or Claude Sonnet 5, medium effort.

Apply only `qa-editorial.json` fixes. Approval is a no-op; do not perform a new
full editorial analysis. Fixes explicitly target `edl`, `captions`, or `style`;
all paths and resulting artifacts validate before any write. Update affected artifacts, render a new
preview if substantive, rerun technical QA, render `final.mp4`, fully decode it,
and verify duration, CFR, A/V timing, captions, ending, and destination. Require
passing `qa/qa-brand.json` before Stage 4 completes. Persist state.

## Stage 5 — optional delivery

Recommended tier: `mechanical_fast`.
Current recommendations: OpenAI Luna or Claude Haiku 4.5, low effort.

Use `social-video-agent deliver WORKSPACE --output DESTINATION` with desired
variant flags. Create only approved mechanical variants: no-captions, SRT/VTT,
poster, composed `--cover`, validated `--publish` metadata, names, and
`delivery-manifest.json`. `--platform` adds safe-zone and length checks for the
destination; see [publishing.md](publishing.md). Composing a cover and writing
publishing copy are editorial acts: do them in Stage 4 or earlier if the wording
matters, not as a mechanical afterthought. Every video gets QA and
every item gets size, format, SHA-256 and status. Verify the EDL hash before and
after; Stage 5 must not change cuts or story, and `/tmp` is not a delivery target.

## Resume and failure behavior

Each edit has its own workspace and state. On a new conversation locate the
workspace, run status, report the active stage and missing artifacts, then
continue. Malformed/unknown schemas stop with an actionable error. Never infer
completion from chat history or from a file's mere presence without validation.
