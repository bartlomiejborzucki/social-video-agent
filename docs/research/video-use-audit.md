# Audit: browser-use/video-use

**Reviewed at** `9575612f066aa517354790a645fd90f9f95a743b` (HEAD of `main`)
**Review date** 2026-09-15
**License** MIT, Copyright (c) 2026 Browser Use
**Activity at review** 24,918 stars, 3,019 forks, 99 open issues, 78 open pull
requests, last push 2026-08-30

Read in full: `README.md`, `SKILL.md`, `install.md`, `pyproject.toml`, all five
helper scripts, both tests, the vendored `skills/manim-video/`, plus the open and
closed issue and pull request lists.

---

## What it is

A skill, not a library. 1,761 lines of Python across five standalone scripts in
`helpers/`, invoked as `python helpers/<name>.py`. `pyproject.toml` declares
`py-modules = []`, so `pip install` produces an empty distribution: **nothing in
this project is importable**. The intellectual weight is in `SKILL.md` (322
lines, 23 KB), not in the code.

| file | lines | role |
|---|---|---|
| `helpers/render.py` | 771 | cut, concat, composite, subtitle, loudness |
| `helpers/timeline_view.py` | 392 | diagnostic filmstrip + waveform PNG |
| `helpers/grade.py` | 375 | colour presets and auto-grade |
| `helpers/transcribe.py` | 241 | ElevenLabs Scribe |
| `helpers/pack_transcripts.py` | 206 | phrase-level compact transcript |
| `tests/` | 206 | fps parsing and orientation only |

---

## What it solves well, and that we keep

These are good decisions, and we adopted all of them.

1. **Transcript-first reasoning.** The agent reads a compact phrase-level
   document rather than raw token JSON. This is the central insight of the
   project and it is correct.
2. **A compact packed transcript as the agent's primary surface.**
3. **Visual inspection only at decision points**, never frame-by-frame.
4. **An explicit EDL** as the boundary between reasoning and execution.
5. **Immutable sources, separate `edit/` workspace.**
6. **Word-boundary cuts** as a stated rule.
7. **Short audio fades around every cut.** 30 ms is the right number.
8. **Self-evaluation of rendered output**, with a bounded repair loop.
9. **Persistent project memory** in `project.md`.
10. **Separation of agent reasoning from deterministic media execution.**

Specific code worth keeping verbatim, and which we ported with attribution:

- `render.py:175-228` — `parse_fps` and `probe_source_fps`. Exact rational
  handling, idempotent, bounded by the int32 limits of `AVRational`,
  length-capped against a pathological input, and prefers `avg_frame_rate` over
  `r_frame_rate` for variable-frame-rate footage. The best code in the project.
- `render.py:135-172` — rotation-aware portrait detection. Correctly reads the
  display matrix rather than the legacy `tags.rotate`, with the reasoning
  documented.
- `render.py:96-132` — the HDR→SDR tone-map chain. A textbook-correct zscale
  chain.
- `render.py:491-594` — two-pass loudness at −14 LUFS / −1 dBTP / LRA 11.
- `render.py:44-51` — the caption safe-zone rationale. The single best piece of
  domain knowledge in the repository.
- `pack_transcripts.py` — the whole file. Zero third-party dependencies, clean,
  and it does its job.

---

## What is broken, and what we changed

### Transcription is welded to one paid API

One hardcoded URL, one hardcoded model id, one environment variable. There is no
local path, no fallback, and no abstraction. `SKILL.md:312-313` actively
instructs the agent *not* to use Whisper.

This is not an oversight that is about to be fixed. Local transcription has been
submitted **six separate times** — PRs #4, #12, #22, #28, #60, #151, plus #114
(Groq) and #130 (Grok) — and every one is closed or sitting open. The project
merges roughly 9 of 87 pull requests ever opened.

**Ours:** a provider protocol with `validate_setup()` checked before any audio is
extracted, faster-whisper as the default, and no API key required for anything.

### The cache cannot detect a changed source

```python
out_path = transcript_path(edit_dir, video, audio_track)
if out_path.exists():
    return out_path
```

The key is the filename stem. No hash, no size, no mtime. Re-exporting a source
silently reuses the stale transcript; two files with the same stem in different
folders collide; `--language` and `--num-speakers` are not part of the key, so
changing them returns the previous result. `SKILL.md:30` states the rule the code
cannot implement.

**Ours:** content fingerprint (size plus both ends of the file) combined with an
options fingerprint, in a content-addressed cache — so switching model and
switching back is free, and `touch` does not invalidate.

### There is no 9:16 anywhere

No `crop`, no `pad`, no aspect-ratio change exists in the repository. For a tool
being used to make social video this is the largest functional gap.
`SKILL.md:266` tells the agent to "pass `--filter`" — a flag `render.py` does not
have.

**Ours:** a reframe abstraction with fit, centre, face-aware, and speaker modes,
producing an inspectable crop plan with keyframes.

### Encoding bugs that were fixed once and missed elsewhere

`write_text()` with no `encoding=` at `render.py:375` (concat list),
`render.py:487` (`master.srt`), and `transcribe.py:180` (the transcript, written
*after* the paid API call). Commit `196d7e9` fixed exactly this bug in
`pack_transcripts.py` and the others were never revisited.

### Filter-path escaping is wrong

`render.py:644` escapes `:` and `'` but never `\`, and in the wrong order. Every
Windows path breaks, as does any path containing an apostrophe. There is no test.

We determined the correct scheme empirically against ffmpeg 7.1 (backslash
first, then `:` and `=`, apostrophe last via close-escape-reopen, wrapped in
single quotes) and cover space, apostrophe, comma, bracket, colon, semicolon,
equals, backslash, non-ASCII and combinations with real ffmpeg burn-ins.

`grade.py:109` interpolates a temp path directly into a filter string, which
makes auto-grade — the default mode — structurally broken on Windows.

### Every ffmpeg failure discards its own diagnostic

`check=True` with `stderr=subprocess.PIPE` that is never read, at `render.py:300,
386, 561, 593, 673`; `stderr=DEVNULL` at `transcribe.py:81`, `grade.py:112`,
`timeline_view.py:60`. An agent debugging a failed render gets a bare
`CalledProcessError`. This is the highest-impact defect for day-to-day use.

Three broad `except` blocks silently substitute defaults: `render.py:34` (a
failed import makes every colour preset a no-op), `render.py:163` (a probe
failure assumes landscape, so a portrait phone clip renders 1920×3413),
`grade.py:154` (a failed analysis is indistinguishable from "already perfect").

### The stream-copy optimisation is spent immediately

Each range is encoded to its own file, concatenated with `-c copy`, then the
whole timeline is **re-encoded** as soon as there are captions or overlays —
which is the normal case. Audio is encoded twice. And `--draft` and `--preview`
both composite at a hardcoded CRF 18, so draft mode is far slower than
advertised.

**Ours:** one input per range with fast seek, one `filter_complex`, one encode.

### Mixed orientations produce an undecodable file

`is_portrait_source` is evaluated per segment while frame rate is deliberately
unified for the whole render — with a comment explaining why uniformity matters
for `-c copy`. That reasoning was never applied to dimensions, so a portrait and
a landscape clip in one EDL are concatenated at different resolutions.

### There is no EDL schema

The only definition is a prose example in `SKILL.md:268-289`, read by raw dict
indexing. `version` and `total_duration_s` are documented and **never read by any
code**, so the "duration matches expectation" check is manual. `quote` and
`reason` are likewise never read. Nothing validates `end > start`, source
existence, or in-bounds ranges, and `resolve_grade_filter` passes an arbitrary
string straight into `-vf`. The documented example's relative overlay path
resolves incorrectly against the documented workspace layout.

### Caption style is frozen, and the documentation contradicts the code

Two-word chunks, forced uppercase, `FontName=Helvetica` (macOS-only; libass
silently substitutes elsewhere), size fixed against libass's 288-line virtual
canvas so it means different things at 1080p and 4K. Meanwhile `SKILL.md:180-195`
invites the agent to design caption styles freely — and Hard Rule 12 forbids
writing into the skill repository, so there is no legitimate way to change them.

`MarginV` is 90 in the code and **35 in `SKILL.md:184` and `:190`**. An agent
following the documentation places captions in the platform UI dead zone, which
is the exact failure the code comment warns about.

### Self-evaluation is prompt text with no implementation

Zero lines of code. It asks a vision model to spot a 30 ms audio pop in a
filmstrip — and `timeline_view` normalises its waveform per window, so a pop
quieter than the loudest speech in view renders as a small blip. The three-pass
cap is enforced by nothing. The "verify duration matches the EDL" step needs
`total_duration_s`, which no code writes or reads.

**Ours:** mechanical checks first (duration against the EDL, clipping, black
frames, silence at cut boundaries, caption overlap and placement), with stills
generated only where those checks point, and a persisted attempt counter.

### Smaller things

- `librosa` and `matplotlib` are declared dependencies and never imported.
  `librosa` alone pulls in numba and llvmlite.
- Two ffprobe subprocesses **per EDL segment**, unmemoised.
- `timeline_view` spawns one ffmpeg **per frame**; its font list has no Windows
  paths and falls back to an ASCII-only bitmap font.
- `VIDEO_EXTS` is a literal case-sensitive set, so `.M4V`, `.webm`, `.mts` and
  `.Mp4` are silently skipped; directory scanning is not recursive.
- `pack_transcripts` reports the speech span as "duration", so a clip with a
  silent lead-in is described as shorter than it is.
- No phrase length cap, so continuous speech collapses to one unusable line.
- The vendored `skills/manim-video/` has no Python, no integration, and a stale
  internal path. Dropped: LaTeX-dependent maths diagrams are not on the path for
  social video.

---

## Which gaps the ecosystem has already addressed upstream

Open pull requests we verified as pointing at real defects, none merged:

| area | PRs |
|---|---|
| Local transcription | #4, #12, #22, #28, #60, #114, #130, #151, #152, #160 |
| Windows paths, encoding, fonts | #78, #79, #81, #103, #110, #112, #116, #117, #124, #126, #127, #128, #131, #135, #139, #143, #144, #149 |
| Preflight / doctor | #129 (issue #121) |
| Vertical output | #104 |
| fps parameterisation | #27, #31, #122 |
| Per-source probe caching | #150 |
| Caption style on the EDL | #159 |
| Path traversal in `resolve_path` | #93 |

Open issues confirming the same: #118 (subtitle burn-in crashes on a documented
macOS install and renders tofu for non-Latin text), #125 (UnicodeEncodeError on
non-UTF-8 stdout), #121 (no preflight), #162 (audio click at segment boundaries
from AAC priming with `-c copy` concat).

Issue #162 is worth noting: it describes a defect our architecture does not have,
because we never stream-copy concatenate encoded segments.

---

## What we would offer upstream

Generic and self-contained, if the project becomes receptive:

- `encoding="utf-8"` on the three `write_text` calls.
- The empirically-derived filter-path escaping, with its test matrix.
- Reading and surfacing ffmpeg's stderr on failure.
- Memoising the per-segment probes.
- Correcting the `MarginV` drift between `SKILL.md` and `render.py`.

Given 9 merges out of 87 pull requests, we treat upstreaming as a courtesy
rather than a plan, and do not let our roadmap depend on it.

## What stays ours

Social-specific behaviour: vertical reframing, clip discovery and scoring,
caption styling and brand profiles, output profiles, the mechanical QA suite,
and the provider architecture.
