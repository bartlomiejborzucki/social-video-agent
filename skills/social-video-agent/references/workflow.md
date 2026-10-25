# Persistent editing workflow

`workflow-state.json` is the cross-model and cross-conversation router. Read it
before doing work. After completing a stage run `workflow complete N`; this
validates artifacts and advances state. `workflow status WORKSPACE` (or
`-w WORKSPACE`) reports missing files with the command that makes each one,
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

Stage 1 writes `analysis/<source>.transcript-quality.json`. When it is not
`ok` (music notes or sound annotations over 20% of tokens, many low-confidence
words, a phrase looping, an English-only `.en` model on other speech, or an
uncertain language), tell the user what it found before planning cuts on that
transcript and offer the `suggested_model` re-run (`--model <m> --force`). It
is their call: a larger model costs minutes on a CPU.

It also lists `suspect_words`: a word longer than 1.2 s, or one the sound goes
quiet inside for 0.3 s or more. That is whisper folding a false start and its
pause into the next word ("zawsze" over 51.4–55.3 s) or sliding a run of
words. Re-transcribe only those passages; `refine` lists them ready to paste:

```bash
social-video-agent transcribe SOURCE -w WORKSPACE --refine 51.0-56.0 --model large-v3
```

The passage's words replace the old ones in `transcripts/<id>.json`, gaps are
re-synthesised and the change is printed (`was` / `now`). Never paste words
into a transcript by hand.

`transcripts/<id>.json` is the source of truth for every recording: `compile`,
`cuts`, `motion suggest` and `plan` read it whatever model made it, and the
cache under `cache/transcripts/` only fills it. A correction made there
reaches the edit; `transcribe --force` is the way to start over.

Run `config validate PROJECT --workspace WORKSPACE` when project config is
present. It creates executable `brand-contract.json`; missing required
font/logo assets or mixed CLI/skill/plugin versions block the workflow before
editorial work. Without `--workspace` it validates and writes nothing. It also
lists each style decision left to a schema default (`motion_energy`,
`style_pack`, `label_style`, karaoke, word animation, brand words): tell the
user, and offer to write the choice into the config.

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
context or reinterpret the story without a concrete execution conflict. If the
request came with a montage brief, `brief import` it before building captions.
Start the first range on the scene, so frame 0 has the person or the action and
no more than `max_leading_silence_s` of silence ([opening.md](opening.md)).
Create the exact `edl.json`, captions, and 9:16 framing. `social-video-agent compile
SOURCE -w WORKSPACE` builds a word-aligned `edl.json` from the plan, accepted
cuts included; it refuses to overwrite an existing EDL without `--force`.

`compile` then moves each range's outer edges from the word times to where the
speech is heard to start and stop (RMS against the local noise floor, within
0.4 s of the word), keeping a 0.08–0.12 s breath and never crossing a
neighbouring word. Whisper ends words early (the last syllable of "wieczorem"
was cut, leaving an open mouth) and glues silence onto a first word (dead air
at the opening); both are fixed here, and every move is printed under "Edges
moved to the speech" and noted in the range's `reason`. A warning says when
speech carries on past the final out-point. `--word-edges` keeps the
transcript's edges.

`zoom`, `speed` and `grade` on a plan item are carried onto every range it
compiles to, so a fix such as a sharp 1.1 framing jump belongs in the plan,
not in a hand edit of `edl.json`. `compile` lists any `qa-editorial.json` EDL
fix the rebuilt EDL no longer carries. For the default renderer also
write `motion-plan.json`: run `motion suggest`, accept the accents that serve
the story, add the graphics it cannot see, and keep the rhythm the project's
`motion_energy` asks for (see motion-design.md). Every graphic keeps its
reason. FFmpeg first creates the frame-accurate base edit;
Remotion composites the approved motion layer; then FFmpeg/ffprobe QA the final
`preview.mp4`. Write `qa/qa-technical.json`, stop, and hand off for editorial
review.

Before a render, tell the user how long it will take when `render` prints an
estimate (`--json`: `estimate.seconds`). It comes from earlier renders on this
machine; with no history there is none, so do not invent one.

When the contract asks for an active-word highlight, the caption track must
carry word timings: the renderer records the features it actually drew and brand
QA fails if a contracted one was dropped.

### One reel from several recordings

A scripted reel is often several files: takes of the speaker, a cutaway, a
child's line recorded on its own. Start with one (`workflow init FILE --id
kamera`), add the rest to the same workspace with `sources add FILE -w
WORKSPACE --id ID` (probed and fingerprinted; transcripts and state are left
alone; `sources list -w WORKSPACE` shows them), `transcribe` each one with
sound into it, then write one plan. Each kept item names its `source` and its
`order` in the reel. `audio_source`, `audio_start` and `audio_end` put another
file's sound under the item's picture (a voice off camera); the picture is
trimmed to the voice, and a voice longer than the picture is refused with the
end it needs. `speed` below 1 slows only the picture under such a voice
(a playground clip at 0.88 under a longer sentence); the voice keeps its own
pace and length, and the error names the speed that would fit. `grade` gives
the item a named look: `mono`, `mono_contrast`, `shake`, combined with `+`
(`mono_contrast+shake` for a remembered, shaky scene). An unknown grade is
refused; never prepare a black-and-white derivative file. `reframe` fixes a crop for the item, in source pixels as
displayed, which `reframe` then leaves alone. `beat` names the scene, and a
label with the same text is pinned to it.

```bash
social-video-agent compile -w WORKSPACE --force
```

The source argument is optional with `-w`, and may be a picture with no sound
of its own. `compile` loads the transcript of every recording the plan keeps words from
(it says which one is missing), builds the EDL in `order`, writes one caption
track numbered across all of them (`captions/main.json`, `.srt`, `.vtt`,
`.ass`; `--no-captions` skips it) and pins the motion plan's labels to the
scenes it made. Never write `edl.json` or merge caption files by hand.

To correct a misheard or reworded caption, change the words, never the times:

```bash
social-video-agent captions fix -w WORKSPACE --at 6.9 --from "sam." --to "już."
```

It updates the cue and its words (the karaoke highlight draws from the words)
and rewrites the JSON, SRT, VTT and ASS. `caption_hold_through_pauses: true`
keeps each caption up through a pause within one range.

Generate captions from the compiled brand contract. The EDL stores its
fingerprint, never an unresolvable project/profile name. Rounded caption boxes are drawn by
both renderers from the same measured layout; on the FFmpeg route libass draws
them with the brand font loaded from the project, so a project that cannot use
Remotion keeps its caption contract.

## Stage 3 — supervising-editor review

Recommended tier: `editorial_strong`.

For a Remotion render, measure the motion layer first, then look at it:

```bash
social-video-agent motion qa -w WORKSPACE
social-video-agent motion sheet -w WORKSPACE
```

Advisory short-form findings come from `social-video-agent reel-check
WORKSPACE` ([short-form.md](short-form.md)); read them with the motion QA.

`motion qa` writes `qa/qa-motion.json`, which Stage 3 requires on the Remotion
route: per graphic, its time on screen against the time to read it, its
overlap with the caption band while words are spoken, and the share of a face
it covers on the base render; then accents per minute against the energy
level, and the longest stretch with no cut, graphic, punch-in or transition.
Every finding is a warning with measured and expected values. `motion sheet`
then colours each tile green, amber or red by those findings. Fix what you
agree with, or accept a deviation by name in `accepted_qa_warnings` and say
why in the review.

`motion qa` also warns when a transition runs over speech while a face is on
screen -- a blurred or zoomed mouth that keeps moving reads as audio out of
sync -- and reports each scene title's size in the frame tab.

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
Current recommendations: OpenAI Sol or Claude Sonnet 5.5, medium effort.

Apply only `qa-editorial.json` fixes. Approval is a no-op; do not perform a new
full editorial analysis. Fixes explicitly target `edl`, `captions`, or `style`;
all paths and resulting artifacts validate before any write. Update affected artifacts, render a new
preview if substantive, rerun technical QA, render `final.mp4`, fully decode it,
and verify duration, CFR, A/V timing, captions, ending, and destination. On the
Remotion route technical QA measures `audio/video sync against base`: the
sound and picture of the delivered file against the base render they were
composited over, failing beyond 20 ms. Require passing `qa/qa-brand.json`
before Stage 4 completes. Persist state.

## Stage 5 — optional delivery

Recommended tier: `mechanical_fast`.
Current recommendations: OpenAI Luna or Claude Haiku 5.5, low effort.

Use `social-video-agent deliver WORKSPACE --output DESTINATION` with desired
variant flags. Create only approved mechanical variants: no-captions, SRT/VTT,
poster, composed `--cover`, validated `--publish` metadata, a variant per
translated caption language (`--language`), names, and
`delivery-manifest.json`. Under `content_first` the composed cover is always
delivered as `cover.jpg`, and the opening is measured into the manifest; a
delivery whose opening breaks the rule is not ready and Stage 5 cannot
complete. See [opening.md](opening.md). `--platform` adds safe-zone and length checks for the
destination; see [publishing.md](publishing.md). Composing a cover and writing
publishing copy are editorial acts: do them in Stage 4 or earlier if the wording
matters, not as a mechanical afterthought. Every video gets QA and
every item gets size, format, SHA-256 and status. Verify the EDL hash before and
after; Stage 5 must not change cuts or story, and `/tmp` is not a delivery target.

`--max-size-mb 30` keeps every delivered video under a size (some routes to a
phone refuse anything larger): a larger one is re-encoded in two passes at
the bitrate its length and audio leave, the audio stream is copied untouched,
and A/V against the file it replaced is checked. The manifest item records
`size_limit_bytes`, `video_bitrate_kbps` and `av_error_ms`.

## Several recordings at once

```bash
social-video-agent workflow batch RECORDINGS_DIR -w PARENT --project-root PROJECT
social-video-agent workflow status PARENT
```

Each video directly in the folder gets its own workspace under the parent,
through the ordinary Stage 0, and is edited through every stage on its own.
`workflow status PARENT` lists where each one stands and which to work on
next, and warns when the recordings no longer compile the same brand contract:
validate the config in each workspace before rendering if it does. Clip
selection stays editorial per recording.

## Resume and failure behavior

Each edit has its own workspace and state. On a new conversation locate the
workspace, run status, report the active stage and missing artifacts, then
continue. Malformed/unknown schemas stop with an actionable error. Never infer
completion from chat history or from a file's mere presence without validation.
