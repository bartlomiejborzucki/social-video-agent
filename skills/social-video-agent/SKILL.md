---
name: social-video-agent
description: Create project-aware Reels and Shorts from recordings with local transcription, an explicit plan and EDL, persistent stages, rendering, and QA. Use when asked to edit, trim, caption, reframe, review or resume a preview, or create delivery variants. Do not use for generated video or simple conversion.
license: Apache-2.0
metadata:
  version: "2.5.0"
  last_updated: "2026-10-20"
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
   --workspace WORKSPACE` (without `--workspace` it writes nothing). It names
   every style decision the config leaves to a default -- `motion_energy`,
   `style_pack`, `label_style`, the karaoke highlight, word animation, brand
   words. Tell the user: a default is a choice nobody made, and `config init`
   asks for each one. Treat `brand-contract.json` as executable input and
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

5. Read [workflow.md](references/workflow.md) plus only the active stage's
   relevant reference below. Use [model-routing.md](references/model-routing.md)
   for handoffs.
6. In guided mode validate and save artifacts, stop at the boundary, recommend
   the next model, and give the exact continuation prompt in the user's
   language. The skill cannot switch models.

Use `social-video-agent workflow status WORKSPACE --json` for “Where are we?”
and resume requests; `workflow brief` (also the Claude session-start hook)
lists the edits in progress under the project.

## Content first: the opening

Frame 0 is the scene, never a card. In September 2026 a parenting brand's
weakest reels lost viewers at one second, where a cover pasted into the
timeline cut to the speaker. The best one opened on the action with the
situation captioned from frame 0. So, by default (`opening_policy:
content_first`):

- **No card at the start.** There is no title card, cover, logo, black or
  white frame at the start, and no silence over `max_leading_silence_s`
  (0.3 s). An end card belongs only at the end.
- **The first caption starts at 0.0 s** and carries the whole first sentence
  of the situation, up to `first_cue_max_words` (8) on at most two lines. This
  is the one exception to `max_words_per_cue` and `max_chars_per_cue`.
- **The cover is `delivery/cover.jpg`,** set on IG, FB, TikTok and YouTube at
  publication. It is never in the timeline:
  `social-video-agent cover WORKSPACE --from-brief`.
- **A montage brief overrides the defaults** (Nagranie / Scenariusz with "Co
  mówisz" and "Napis na ekranie" / Montaż / Okładka). Import it first with
  `brief import FILE -w WORKSPACE --labels`. Its first row is the first
  caption. Short texts like "Spróbuj tak" are `label`s over the shot, not
  cards. "Okładka" only makes `cover.jpg`. A child's line the recording lacks
  is shown as text, never voiced.
- **`deliver` checks the opening** and writes the result into
  `delivery-manifest.json`: `first_frame_is_content`, `first_frame_note`,
  `first_cue_start_s`, `first_cue_text`, `leading_silence_s`,
  `cover_in_timeline`, `time_to_first_situation_s`, `end_card_only_at_end`,
  `opening_ready`, `opening_issues` and `cover_path`. A broken rule means the
  delivery is not ready: say what to fix and propose the variant.
  `opening-qa WORKSPACE` runs the same check at any stage. Look at
  `analysis/first-frame.png` and pass `--first-frame-note`.

The config keys, with these defaults when absent: `opening_policy:
content_first`, `cover_in_timeline: false`, `first_cue_full_sentence: true`,
`first_cue_max_words: 8`, `max_leading_silence_s: 0.3`. The full rules, a brief
example and every manifest field are in [opening.md](references/opening.md).

## Scenes, labels and the cut

The house rules for a scripted reel, from the 13.10.2026 decisions:

- **No card at the start.** The hook is the scene and the whole first caption
  from 0.0 s (above).
- **A scene label is never drawn like a caption.** With `label_style:
  scene_frame` it is the title of a frame around that scene's captions; when
  one scene hands over to the next, the frame stays and the title flips. Set
  `caption_hold_through_pauses: true` so the frame is never empty. With the
  default `chip` it is a pill in the top zone, never in the caption colour.
- **A push-in every 3-5 s** (at most the energy's `punch_in_max`), and `zoom`
  transitions on cuts; `slide` is allowed but busier.
- **A call to action only at the end**, when the publish copy asks for a save or
  a send; inside a scene frame put it at `position: top`. A summary list sits
  over the upper zone with `position: top`, off the face.

A reel cut from several recordings -- takes of the speaker plus a child's line
recorded on its own -- is one plan: each item names its `source` and `order`,
`audio_source`/`audio_start`/`audio_end` put a voice under another file's
picture, and `reframe` fixes a crop. `compile` builds the EDL, one caption
track from every transcript, and pins the brief's labels to the scenes it made.
Correct a misheard caption word with `captions fix -w WORKSPACE --at SECONDS
--from OLD --to NEW`; never edit the caption files by hand. Details:
[motion-design.md](references/motion-design.md) and
[workflow.md](references/workflow.md).

Never work around the tool by hand; each of these is a feature:

- A new file for the edit: `sources add FILE -w WORKSPACE --id ID`.
  `compile -w WORKSPACE` needs no source argument, and a picture without sound
  is fine when the plan's voice is transcribed.
- `transcripts/<id>.json` is the truth for every recording. Words the sound
  contradicts are listed with a span: `transcribe SOURCE --refine START-END
  --model large-v3`.
- `compile` puts range edges on the heard speech and prints every move.
- A slowed picture (`speed`), a look (`grade: mono_contrast+shake`) and a
  sharp framing jump (`zoom`) go on the plan item; never a derivative file.
- No transition over a talking mouth inside one take: accept the `jump`.
- An end card after the last word is `hold: true`, never a clip in the plan.
- `deliver --max-size-mb 30` when the file must stay small; the audio is
  copied untouched, and QA holds A/V to the base render within 20 ms.
- A reaction on a word is a `sticker` (allowlisted emoji or project image) and
  a `shake`, both `at_word`; never in frame 0, never on the end card.
- Judge the opening with `hook check` and test lines with `motion variants
  --from-brief`; open on movement and `--hook-punch`, never with a card.
- B-roll comes from the project library described in `broll.yaml`; a clip with
  a child's face is never proposed.

## What helps a reel travel

No edit guarantees reach. What it can do is avoid the known ways of losing a
viewer: the situation heard within a second, a picture that changes every three
to five seconds, no dead air, every word captioned, an end right after the
payoff, a length in the platform's completion window, and copy that honestly
asks for a save or a send. `social-video-agent reel-check WORKSPACE` measures
these as advisory warnings; `deliver` records them as `reel_check` and
`reel_check_warnings`. Read [short-form.md](references/short-form.md) before
Stage 3, and judge each finding against the story rather than chasing a score.

## Modes and invariants

Default `guided` route uses the OpenAI or Claude recommendation returned by
workflow status for every active stage, including Stages 4 and 5. OpenAI's
route is Astra → Sol → Astra → Sol → Luna; Claude alternatives are
defined in the same central mapping. The escalation tier (Claude Fable 5.1) is
exceptional only and is never chosen automatically. “Use this model for everything” or
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
- For every Remotion workflow, Stage 2 writes `motion-plan.json`, built from
  `motion suggest` candidates the agent accepts plus graphics it adds, sized to
  the project's `motion_energy`. Read [motion-design.md](references/motion-design.md).
  When the user shows a reference video, measure it with `style analyze` and
  borrow only its rhythm.
  Remotion enriches an approved edit; it does not decide the story or repair
  insufficient footage.
- A full-frame graphic may instead be authored as a Claude Motion film, only
  when your own tool list has the Motion artifact type. The CLI writes the
  spec, you write the film, the user exports it, the CLI imports it. Never
  upload the recording; brand files go up only under `brand_asset_upload` or
  `--allow-brand-upload`. Without the Motion type (Codex, most hosts) draw the
  same card with Remotion and say so; never fail the brief over it. Read
  [motion-film.md](references/motion-film.md).
- Stage 2 compiles project config into `brand-contract.json`; render only a
  matching EDL/contract. Stage 4 requires technical QA and `qa/qa-brand.json`.
- Music and effects are not gated: `audio_bed` and `sound_effects` need no
  licence declaration, and `music_policy`/`sfx_policy` are recorded preferences
  the renderer does not enforce. Read [audio.md](references/audio.md).
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
  folder, then `image register` it. Under the default
  `image_generation_policy: ask` ask the user for each image and record the yes
  (`--user-request`); never a realistic child, never text in the image. Record no model name unless the tool gives
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
| Several recordings in one batch | [workflow.md](references/workflow.md) |
| Captions in another language | [style.md](references/style.md) |
| The workflow as MCP tools | [mcp.md](references/mcp.md) |
| Setup/render failures | [troubleshooting.md](references/troubleshooting.md) |
| Agent on Windows, engine in WSL2 | [hybrid-runtime.md](references/hybrid-runtime.md) |
| The opening, the cover and the montage brief | [opening.md](references/opening.md) |
| Short-form practices, length, reach | [short-form.md](references/short-form.md) |
| Hook card, graphics, punch-ins, transitions, b-roll | [motion-design.md](references/motion-design.md) |
| Hook, chapter or end card designed in Claude Motion | [motion-film.md](references/motion-film.md) |

After project rules and user overrides, work in this order: meaning, clarity,
clean cuts, audio, framing, captions, then motion. Then give the cut rhythm:
something should change every 3–5 seconds — a cut, a punch-in, a graphic, a
caption accent — at the project's `motion_energy`. Motion always serves the
words on screen; it never decorates silence. Technical
success is not editorial approval: Stage 3 must inspect the opening sheet, hook,
story, cut boundaries, final ten seconds, dense final-five-second sheet, last
frame, and motion/audio ending, then always write valid `qa-editorial.json`.
