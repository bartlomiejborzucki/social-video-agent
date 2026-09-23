# Roadmap

Reviewed **2026-09-23** against 0.6.3. This is a direction, not a commitment:
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

The common gaps against that field are animated word-level captions,
filler-word and retake removal, punch-in zoom, active-speaker framing and
per-segment layouts, NLE export, and URL ingest.

## 0.7 — stabilisation (done)

Remotion from an installed wheel, one atomic writer, named probe failures, the
full Python matrix with coverage and a type-checked 3.10 floor, PowerShell lint,
path property tests, and the CLI and renderer split into smaller units. See the
changelog for detail.

## 0.8 — edit quality (done)

Brand keyword emphasis and the active-word highlight from project config, with
both renderers drawing the same thing; cut candidates the agent accepts by id
and a `compile` command that removes them exactly; a WhisperX forced-alignment
backend; timed punch-ins held to the brand's movement limit.

## 0.9 — framing and layout (done, one item moved)

Speaker diarization with the user's own token, speaker framing that follows
diarized turns and cuts between faces at turn changes, and stacked layouts for
two speakers or a screen above the presenter.

Moved to "Under consideration": neural active-speaker detection (LR-ASD). It
needs a PyTorch port of the model, its weights and a labelled clip set to prove
the port matches the reference, none of which CI can carry; diarized turns
already resolve the two-hander case it was meant for.

## 1.0 — integration (done, one item moved)

NLE export to FCPXML, Premiere XML, OpenTimelineIO and CMX 3600, read back by
OpenTimelineIO in CI; optional URL fetch with the user's rights statement and a
provenance record; PyPI publishing through trusted publishing, off until the
PyPI project is configured. Publishing metadata was already carried by
`publish.json` and `deliver --publish`.

Moved to "Under consideration": direct upload to platforms. It needs each
platform's credentials and publishes on the user's behalf, which is a larger
decision than an export.

## 2.0 / 3.0 — long term

Not resourced today.

- An MCP server exposing workflow stages as tools, to reach agents beyond Codex
  and Claude.

## Under consideration

- Neural active-speaker detection (LR-ASD, MIT), behind an optional extra.
- Direct, opt-in upload to platforms using the user's own credentials.
- B-roll from the user's own library, matched to the transcript.
- Caption translation (no dubbing).
- Batch processing of several recordings.
- Automated WSL2 acceptance on a self-hosted Windows runner.
