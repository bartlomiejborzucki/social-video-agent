# Artifacts

Everything the pipeline produces is JSON with a `schema_version`, validated on
read. A malformed artifact fails immediately and names the offending field
rather than reaching ffmpeg.

## Workspace layout

```
edit/
  workflow-state.json     persistent stage/model handoff state
  context/
    project-context.json  structured project facts and decisions
    project-context.md    compact human-readable summary
    context-sources.json  ranked source paths, confidence, fingerprints
  project.md              your notes and the user's standing preferences
  source-manifest.json    what the sources are, probed
  transcripts/            canonical transcript per source
  takes-packed.md         the compact view you read
  analysis/               scene detection
  edit-plan.json          editorial intent
  edl.json                exact ranges and render instructions
  motion-plan.json        intentional Remotion motion-design layer
  qa-editorial.json       mandatory supervising-editor decision
  captions/               caption data, .srt, and .ass
  previews/preview.mp4    stable preview artifact
  final/final.mp4         stable delivery artifact
  qa/qa-report.json       canonical technical QA report
  qa/ending-contact-sheet.png
  cache/                  content-addressed; safe to delete
```

## edit-plan.json — intent

```json
{
  "schema_version": 1,
  "goal": "60 second educational Reel",
  "profile": "educational",
  "strategy": "Open on the claim, drop the setup, end on the example.",
  "style_sources": ["docs/video-guidelines.md", "docs/brandbook.pdf"],
  "user_overrides": ["Make this one faster than the calm project default."],
  "items": [
    {"action": "drop", "source": "talk", "start": 0.0, "end": 12.4,
     "reason": "throat-clearing before the real opening"},
    {"action": "keep", "source": "talk", "start": 12.4, "end": 48.0,
     "beat": "HOOK", "reason": "the claim, cleanly delivered"}
  ],
  "open_questions": ["Should the caveat at 2:10 stay?"]
}
```

`drop` items carve away from the whole source. `keep` items select explicitly
and take precedence when present — use them when assembling from moments rather
than trimming a recording.

## edl.json — execution

```json
{
  "schema_version": 1,
  "name": "main",
  "output_width": 1080, "output_height": 1920,
  "default_reframe": "face",
  "ranges": [
    {"source": "talk", "start": 12.44, "end": 47.92,
     "beat": "HOOK", "quote": "the thing nobody tells you is...",
     "reason": "snapped to the start of 'the'; snapped to the end of 'is'",
     "zoom": 1.0, "speed": 1.0, "audio_gain_db": 0.0}
  ],
  "captions": "edit/captions/main.ass"
}
```

Rules that hold:

- `end` must be greater than `start`, and ranges must lie inside the source.
  Both are checked before rendering.
- `audio_track` selects which audio stream to render. It is set from whichever
  track was transcribed; changing one without the other gives you captions for
  audio that is not in the output.
- Range durations are aligned to whole frames at render time, so the output
  length does not drift as cuts accumulate.
- Output dimensions must be even.
- `output_fps: null` selects a compatible social CFR (30, 29.97, 60, or 59.94)
  from the nominal source rate. Phone VFR averages are never copied to output.
- The same EDL renders identically every time.

### Separate audio and privacy-safe visual endings

Legacy `source`/`start`/`end` remains valid. A range may instead override
`video_source`, `audio_source`, and their independent start/end values. A hard
`max_visual_source_time` is the privacy stop: the renderer cannot emit a source
frame after it.

When audio outlasts the primary safe image, the EDL must fill the exact gap:

```json
{
  "source": "justyna",
  "start": 0.0,
  "end": 10.86,
  "video_end": 7.10,
  "audio_source": "5",
  "audio_end": 10.86,
  "max_visual_source_time": 7.10,
  "visual_fill_strategy": "secondary_video",
  "secondary_video_source": "safe-broll-2",
  "secondary_video_start": 2.0,
  "secondary_video_end": 5.76,
  "visual_fill_reason": "Continue with approved B-roll after the privacy stop."
}
```

Other explicit values are `end_card` (with `end_card_source/start/end`) and
`intentional_hold` (with `freeze_at` and `freeze_duration`). An unapproved hold
may not exceed `max_static_hold`, which defaults to 0.75 seconds. A longer hold
requires `intentional_hold: true` and a written reason; QA still reports it.
Without a strategy the EDL fails validation instead of extending the last frame.

Edit it by hand freely. Re-render with `social-video-agent render WORKSPACE`.

## motion-plan.json — motion design

The default renderer requires a separate visual plan so effects remain
inspectable and do not leak into editorial decisions:

```json
{
  "schema_version": 1,
  "style": "editorial_clean",
  "accent_color": "#F4C542",
  "text_color": "#FFFFFF",
  "background_color": "#101114",
  "font_family": "Inter",
  "font_path": "/absolute/target-project/assets/fonts/Inter-Regular.ttf",
  "elements": [
    {
      "schema_version": 1,
      "type": "hook",
      "start": 0.2,
      "end": 2.4,
      "text": "Najważniejsza teza",
      "reason": "Make the approved opening understandable without sound."
    }
  ],
  "rationale": "Use the project accent and calm typography; no decorative transitions."
}
```

Allowed element types are `hook`, `lower_third`, `callout`, and `end_card`.
Every element has a bounded timeline interval and editorial reason; an element
outside the video duration blocks rendering. An empty list is valid when
restraint is the professional choice. This plan never changes EDL cuts, audio,
privacy stops, or the source files.

`font_path` is optional and points at a local project-owned TTF, OTF, WOFF, or
WOFF2 file (maximum 20 MB). It is copied only into the private Linux render
staging directory, never into this repository or a release artifact. Confirm
that the project's font license permits its intended rendered use.

## Canonical transcript

One shape regardless of which backend produced it. Tokens are `word`,
`spacing` (an explicit timed gap), or `audio_event`. Gaps are materialised even
for providers that do not report them, so phrasing is consistent.

`has_word_timestamps` reports whether word times are genuinely aligned rather
than an even split of a segment. If it is false, do not place cuts from it.

## Captions

`captions/<name>.json` is the data; `.ass` is what gets burned in. To fix a
misheard word, edit the JSON or the `.srt` and re-render — you do not need to
re-cut. Captions are burned last so nothing composites over them.

## QA report

Checks carry a severity. `error` blocks delivery, `warning` is worth a look,
`info` is a measurement. `attempt` and `max_attempts` bound the repair loop:
when it is exhausted, report what remains rather than continuing.

`qa/qa-report.json` always records one of `passed`, `passed_with_warnings`, or
`failed`, artifact paths, audio/video timing, full decode, and `ending visual
continuity`. The ending check reports the longest near-identical-frame span,
its start/end, and whether the EDL explicitly approved it.

## qa-editorial.json — supervising handoff

Absence is not approval. Write either `{"status":"approved","fixes":[]}` or
`{"status":"changes_requested","fixes":[...]}`. Each fix contains only an
exact EDL `path`, replacement `value`, and `reason`. Unknown status, unknown
fields, empty requested changes, or an approval containing fixes are rejected.
