# Text stories: a sentence per shot, no speech

A text story is a reel without a voice: short sentences, one per shot, a cut
every second or so, often in the second person ("Jesteś na przystanku." /
"Jest 7:30."), ending on a question. The sentences are written by a person in
the brief; nothing is transcribed -- a speech model run on silent shots
invents words -- and the shots' own sound is muted under a music bed.

## Writing it

One line per shot, in a text file:

```text
"Jesteś na przystanku." -> przystanek.mp4
"Jest 7:30." -> zegar.mp4 @ 2.0
"A autobus znowu się spóźnia?" -> droga.mp4 @ 0.5 1.4s
```

`@ 2.0` starts the shot 2.0 s into its clip; a trailing `1.4s` holds it that
long instead of `--cut-every` (1.0-1.5 s, default 1.25). Other lines are
ignored. Every clip must already be a source of the edit (`ingest`).

```bash
social-video-agent brief story story.txt -w WORKSPACE [--cut-every 1.2]
social-video-agent compile -w WORKSPACE        # no transcription
```

`brief story` writes `edit-plan.json` with `mode: text_story` and each item's
`story_text`. `compile` builds one muted range per shot in order and one
caption per shot, on screen for exactly that shot from its first frame, drawn
as `story_caption` says (centred, `font_size_pct: 5` by default, no word
highlight). Add a licensed music bed as for any edit ([audio.md](audio.md)).

## Checks

The opening rules hold: the first sentence is on screen from 0.0 s. Render
evidence records `caption_story`; `reel-check` notes a story whose last
sentence is not a question. `motion suggest` reads speech and has nothing to
read here; place graphics by hand if the story needs any.
