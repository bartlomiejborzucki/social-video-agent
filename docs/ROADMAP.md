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

## 0.7 — stabilisation

- Make the Remotion renderer work from an installed wheel, or fall back to
  FFmpeg with a `doctor` explanation. Today it resolves assets relative to a
  source checkout, and the service and schema disagree on the default renderer.
- Remove transcription backends that are registered but not implemented, and
  the extras that enable nothing yet.
- One filter-path escaper, one atomic writer, one UTC timestamp helper.
- Turn a failed source probe in EDL validation into a named problem instead of
  a raw exception.
- CI: coverage report (threshold later), Python 3.10–3.13 matrix, `--frozen`
  everywhere, PSScriptAnalyzer for the Windows adapter, property tests for
  `paths.py` on both path flavours.
- Split `cli.py` by sub-app and `render_edl` by filtergraph stage; direct tests
  for `transcribe`, `edl/validate`, and `doctor`.

## 0.8 — edit quality

- Animated word-level captions (ASS karaoke or a Remotion component) with
  keyword emphasis driven by the brand config.
- Filler-word, retake, and pause *candidates* derived from word timestamps and
  offered to the agent for approval in the plan — code proposes nothing it then
  applies on its own.
- WhisperX alignment as an optional backend behind the `align` extra.
- Punch-in zoom as a motion-plan or EDL move.

## 0.9 — framing and layout

- Speaker diarization (`diarize` extra) and neural active-speaker detection
  (LR-ASD) in place of the mouth-motion heuristic.
- Per-segment layouts: single crop, two-speaker split, screen share with face.

## 1.0 — integration

- NLE export: FCPXML and OTIO first, then Premiere XML and CMX3600 EDL.
- Optional URL ingest (yt-dlp) with a rights reminder.
- Publishing metadata — title, description, hashtags — written by the agent into
  the delivery manifest; direct platform upload only as an opt-in.
- Publish to PyPI alongside GitHub Releases.

## 2.0 / 3.0 — long term

Not resourced today.

- An MCP server exposing workflow stages as tools, to reach agents beyond Codex
  and Claude.

## Under consideration

- B-roll from the user's own library, matched to the transcript.
- Caption translation (no dubbing).
- Batch processing of several recordings.
- Automated WSL2 acceptance on a self-hosted Windows runner.
