# Roadmap

Reviewed **2026-10-13** against 1.5.0. This is a direction, not a commitment:
items move when evidence changes. The rules in [AGENTS.md](../AGENTS.md) hold
for every item — candidate selection stays editorial, sources stay immutable,
music is never sourced or cleared by the tool, and CI downloads no models.

## Where we stand

Most comparable tools (OpenShorts, ClipsAI, AI-Youtube-Shorts-Generator,
auto-editor, VideoDB Director, Opus Clip, Descript, Submagic, Vizard, Klap)
pick clips and render them in one pass. What they rarely offer, and this
project should protect:

- resumable stages with artifact-gated transitions;
- an inspectable plan and EDL before anything renders;
- automated technical, brand, and platform QA;
- an executable brand contract with a music licence policy.

Public testing of Opus Clip reports roughly 40% of generated clips discarded,
which supports keeping the agent-proposes, human-approves model.

## Shipped (0.7 – 1.5)

Stabilisation (Remotion from an installed wheel, the full Python matrix, CLI
and renderer split); edit quality (brand keyword emphasis, active-word
highlight, `cuts find/accept`, `compile`, WhisperX alignment, punch-ins);
framing and layout (diarization, speaker framing on diarized turns,
`split_stack`); integration (NLE export, `fetch --rights`, trusted
publishing); motion energy (`calm`/`lively`/`bold`, transitions, word
animation, style packs, fifteen graphics); motion from the transcript
(`motion suggest/accept`, beat snapping, sound effects, b-roll, hook variants,
the motion sheet); reference rhythm and transcript trust (`style analyze`, a
transcript unfit to cut on reported with the model to retry); covers, timings
and session start (four cover layouts inside the grid crop, render time
estimates, `workflow brief` and the `SessionStart` hook). See the
[changelog](../CHANGELOG.md) for detail.

## 1.5.1 — hygiene after 1.3 (done)

A patch release.

- Documents that fell behind 1.3 are current: `SKILL.md` numbers its routing
  steps without a gap, and `upstreams.yml` and `.env.example` describe
  WhisperX as implemented.
- Model routing names the current Claude family (Opus 5.5, Sonnet 5.5,
  Haiku 5.5; Fable 5.1 stays the escalation tier). Names only: the file keeps
  its single role as a tier-to-model map.
- The two Remotion integration tests recorded as failing passed once
  reproduced; the failure record was stale.
- What 1.3 added with little cover is tested: the `motion` and `broll`
  commands end to end, property tests that accents never exceed the energy
  level, and beat detection against steady click tempos over a noise floor.
  Those tests found a false beat at either end of a music bed, now fixed.

## 1.6 — Claude Motion segments (done)

On a Claude host with the Motion artifact type, designed full-frame segments —
hook card, intro or chapter card, call to action, end card — can be authored as
a Motion film instead of drawn by Remotion. The CLI writes a film spec from the
motion plan and the brand contract; the Claude session writes the film; the
user exports the MP4 in the browser; the CLI imports it as an immutable, hashed
asset, places it through the existing overlay and end-card paths, and brand QA
checks it against recorded evidence.

- Works on both renderers, so the FFmpeg route gains designed hook and end
  cards without a Remotion licence declaration.
- The recording never leaves the machine. The film carries text and the
  brand's colours; the logo and a brand font file go up only under a recorded
  consent, since they are brand files.
- Codex and Claude hosts without Motion keep the Remotion graphic of the same
  element, and the skill says the bridge is unavailable rather than offering
  it.
- The type's reference confirms a 1080×1920 stage, time in seconds and 24, 30
  or 60 fps. The import's length tolerance defaults to one frame and is an
  option, until a real export confirms the exported length.

Design and rejected alternatives: [ADR-005](architecture/ADR-005-claude-motion-segments.md).

## 1.7 — measured motion QA (done)

Stage 3 judges the motion sheet by eye. 1.7 turns the questions it asks into
measurements in `qa/qa-motion.json`, reported as measured against expected like
platform QA:

- time on screen against the amount of text, per style pack;
- overlap with the caption band, from the measured caption geometry;
- overlap with the tracked face box from speaker framing;
- movement per minute against the energy level's limits.

Motion film segments from 1.6 are included through their registry. Safe-zone
data records when it was reviewed and against which sources, the motion sheet
colours each frame by its verdict, and with the Remotion renderer Stage 3
needs `qa-motion.json` before it accepts the editorial review.

## 1.8 — several recordings, several languages (done, one item moved)

- **Batch:** a folder of recordings becomes one parent workspace with a child
  per recording; `workflow status` reports them together and warns when they
  no longer compile the same brand contract.
- **Caption translation, no dubbing:** the host agent writes the translated
  cues; the CLI validates them against a per-language `max_chars_per_cue`,
  burns them, and delivers SRT, VTT and a variant per language. The CLI makes
  no translation call of its own.

## 2.0 — stages as tools (done, one item moved)

`social-video-agent mcp serve` exposes the workflow stages as MCP tools behind
the same artifact gates: each tool runs the matching CLI command in a child
process, so Codex, Claude and other agents share one implementation. The
user's own acts -- the licence declaration, rights and consents -- are not
tools. The workflow state did not change, so `workflow_version` stays 4.

Moved to "Under consideration": skill files that describe judgement only. A
host without the MCP tools still needs the commands, so the references keep
them.

## Under consideration

- **Skill files that describe judgement only** (moved from 2.0), once every
  supported host reaches the workflow through the MCP tools.
- **An MCP transport over HTTP**, for an agent on another machine than the
  engine. It needs authentication the stdio server does not.
- **Shorts reusing the parent's motion suggestions** (moved from 1.8): accent
  candidates are positions on the parent's cut, so on a child's own cut they
  would land at the wrong times. A child already reuses the parent's
  transcript, so `motion suggest` on the child costs no recognition; reuse
  needs candidates mapped through the source rather than the output.
- **Motion as the whole composite:** uploading the base render to a Motion film
  and exporting the finished short. It needs a media-upload policy with
  recorded consent, an audio re-mux (Motion exports mute picture), captions
  burned afterwards, and acceptance that the result cannot be re-rendered
  locally. Its own ADR before any code.
- Neural active-speaker detection (LR-ASD, MIT), behind an optional extra. It
  needs a PyTorch port, its weights and a labelled clip set CI cannot carry.
- Direct, opt-in upload to platforms using the user's own credentials, after
  the 2.0 tool surface exists.
- Automated WSL2 acceptance on a self-hosted Windows runner.
