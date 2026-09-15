# Artifacts

Everything the pipeline produces is JSON with a `schema_version`, validated on
read. A malformed artifact fails immediately and names the offending field
rather than reaching ffmpeg.

## Workspace layout

```
edit/
  project.md              your notes and the user's standing preferences
  source-manifest.json    what the sources are, probed
  transcripts/            canonical transcript per source
  takes-packed.md         the compact view you read
  analysis/               scene detection
  edit-plan.json          editorial intent
  edl.json                exact ranges and render instructions
  captions/               caption data, .srt, and .ass
  previews/  final/       rendered output
  qa/                     QA reports and diagnostic stills
  cache/                  content-addressed; safe to delete
```

## edit-plan.json — intent

```json
{
  "schema_version": 1,
  "goal": "60 second educational Reel",
  "profile": "educational",
  "strategy": "Open on the claim, drop the setup, end on the example.",
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
- Output dimensions must be even.
- `output_fps: null` means preserve the source rate. Do not set 24 out of habit.
- The same EDL renders identically every time.

Edit it by hand freely. Re-render with `social-video render WORKSPACE`.

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
