# Provenance

What came from where, and how much of it. Every item is traceable to a specific
upstream location and states whether it was ported verbatim, modified, or is
original work.

Nothing here is decoration. If this project is substantially built on someone
else's thinking, that has to be visible.

---

## browser-use/video-use — MIT, Copyright (c) 2026 Browser Use

Reviewed at `9575612`. The primary influence on this project. The full MIT text
is reproduced in [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

### Architecture adopted wholesale

The pipeline shape — source → transcribe → packed transcript → agent reasoning →
EDL → render → QA → revise — is video-use's, as is the central decision to have
the agent reason over a compact transcript rather than raw JSON or video frames.
So are: immutable sources with a separate workspace, an explicit EDL as the
boundary between reasoning and execution, word-boundary cuts, short fades around
every cut, self-evaluation of rendered output with a bounded repair loop, and
persistent project memory.

**We did not invent this shape. We changed what runs inside it.**

### Logic ported, with modifications

| ours | upstream | status |
|---|---|---|
| `ffmpeg/probe.py::parse_fps` | `helpers/render.py:175-198` | **Behaviour verbatim.** Raises `ValueError` rather than `argparse.ArgumentTypeError` so it is usable outside argparse. |
| `ffmpeg/probe.py::_pick_frame_rate` | `helpers/render.py:201-228` | **Logic verbatim** — prefers `avg_frame_rate` over `r_frame_rate` for VFR correctness. |
| `ffmpeg/probe.py::_normalise_rotation` | `helpers/render.py:135-172` | **Concept and reasoning kept** (read the display matrix, not `tags.rotate`). Modified: returns the angle rather than a portrait boolean, and raises on probe failure instead of assuming landscape. |
| `ffmpeg/filters.py::TONEMAP_CHAIN` | `helpers/render.py:96-132` | **Verbatim.** Added a `has_libzimg()` capability check before use. |
| `ffmpeg/filters.py` loudness constants | `helpers/render.py:491-594` | **Values verbatim** (−14 LUFS / −1 dBTP / LRA 11). |
| `ffmpeg/filters.py::audio_cut_fades` | `helpers/render.py:270-272` | **Concept and 30 ms duration kept.** Modified: the fade is clamped to a third of the segment, so a very short range is no longer entirely ramp. |
| `transcript/pack.py` | `helpers/pack_transcripts.py` | **Grouping rule kept** (flush on a long gap or a speaker change). Modified: phrase length cap, interior word offsets for long phrases, media duration rather than speech span. |
| `transcribe/audio.py::guard_not_silent` | `helpers/transcribe.py:62-71` | **Concept kept.** Reimplemented with ffmpeg `volumedetect` rather than parsing samples in Python, which removes an endianness assumption. |
| `schemas/brand.py` caption margin default | `helpers/render.py:44-51` | **Domain knowledge kept** — the rationale for clearing the platform UI dead zone. Expressed as a percentage of output height rather than a fixed value. |
| `skills/social-video-editor/SKILL.md` | `SKILL.md` | **Editorial doctrine adapted** — restraint, meaning first, natural rhythm, the anti-patterns list. Rewritten and restructured; `MarginV` corrected from the stale documented value. |

### Deliberately not carried over

Detailed in [video-use-audit.md](video-use-audit.md). In summary: the
ElevenLabs-only transcription path, the filename-based cache, the
encode-concat-re-encode render architecture, the frozen caption style, the
unvalidated EDL, the prompt-only self-evaluation, the vendored Manim skill, and
`librosa`/`matplotlib` as unused dependencies.

---

## ClipsAI/clipsai — MIT, Copyright (c) 2023 Clips AI, Inc.

Reviewed at `8e73c8a` (2024-01-17, abandoned). **No code was copied.**

Adopted as design: crop is piecewise-constant per segment rather than tracked per
frame; segment boundaries snap against scene cuts; adjacent segments with nearly
equal positions are merged using a dead zone expressed as a fraction of the
frame.

Our `reframe/plan.py` and `reframe/smooth.py` are original implementations. We
clamp the crop window on both axes at both edges — `_calc_crop` upstream clamps
only the low side, so its crop can run past the right or bottom of the frame.

## AgriciDaniel/claude-shorts — MIT

Reviewed at `a369fad` (2026-04-10). **No code was copied.**

Adopted as design: the crop plan as a JSON contract of strategy, crop size and
time-stamped keyframes; and keyframe deduplication thresholded as a percentage
of crop width, which is what makes the setting resolution independent. Reflected
in `schemas/edl.py::ReframePlan` and `reframe/smooth.py::dedupe_keyframes`.

## parleyw/video-use — MIT (see caveat)

Reviewed at `dbfba03`. **No code was copied, and none should be.**

One idea influenced us: separating `validate_setup() -> (bool, str)` from
`transcribe()`, so an unusable backend is detected before any audio is extracted.
Our `transcribe/base.py` is an original implementation of that idea.

Recorded for accuracy: the fork's four Whisper backends fabricate word timestamps
by distributing a segment evenly across its tokens; both diarization backends call
`diarization.iterturn()`, which does not exist in pyannote; and its `LICENSE`
names `parleyw` as sole copyright holder over a tree that is overwhelmingly
Browser Use's work, with no upstream attribution. Anyone adopting from it takes
MIT-licensed Browser Use code under a notice naming the wrong holder.

## WyattBlue/auto-editor — The Unlicense

Reviewed at `1647365` (2026-09-13). **No code was copied.**

Its skill documentation style — trigger-rich descriptions, numbered tasks, option
tables with defaults, explicit gotchas, cross-links between sibling skills rather
than one monolith — shaped how `skills/` is written. Its `v3` timeline format is
recorded as a future export target.

## Remotion

**No code copied, and none may be.** Not open source; see the ecosystem audit.
Its official plugin's skill structure (small, topic-split skills with
progressive disclosure) informed our skill layout. Users are directed to install
the official plugin rather than having its content duplicated here.

---

## Original to this project

Written from scratch, with no upstream equivalent:

- The canonical transcript schema, including synthesised `spacing` tokens so
  every provider produces the same token stream.
- The transcription provider protocol and the faster-whisper backend, including
  the CUDA-runtime fallback that wraps decoding rather than model construction.
- Content-addressed caching on source fingerprint plus options fingerprint.
- All ten Pydantic artifact schemas and their validation.
- The single-pass render architecture (one input per range, one `filter_complex`,
  one encode).
- The empirically-derived ffmpeg filter-path escaping and its test matrix.
- Zero-phase crop smoothing with least-squares edge extrapolation, the temporal
  dead zone, and subject-switch hysteresis.
- Animated crop as a piecewise-linear ffmpeg expression built from keyframes.
- ASS caption generation with a resolution-independent size model.
- Caption timing mapped onto the output timeline, including splitting a word
  that straddles a cut.
- The mechanical QA suite and the bounded, persisted repair loop.
- Word-boundary snapping with silence-bounded padding and range merging.
- The `doctor` command, including the libass, libzimg, font-coverage and
  CUDA-usability probes.
- Output and brand profiles as configuration.
- Cross-agent skill packaging and the installer.
