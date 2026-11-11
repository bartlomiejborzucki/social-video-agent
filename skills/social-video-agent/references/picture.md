# Picture correction and the quality of a source

The picture gets the treatment the voice has: each recording is measured where
the edit shows it, and a correction is applied only when its own threshold is
crossed, scaled to the measurement and stopped at a ceiling. A good recording
is rendered exactly as recorded.

## What a weak source is, and what to say about it

No filter restores detail a file does not hold. A recording sent through a
messenger arrives small and heavily compressed, and that decides how the reel
looks more than anything done in the edit. So the tool says it early, while
the original can still be asked for:

- `inspect`, `sources add` and `workflow init` print a `picture` note when a
  recording will be enlarged at least 1.5x to fill the output, or carries
  under 0.05 bits per pixel (a phone records about 0.15).
- Technical QA repeats it per recording as a warning, `source picture: <id>`,
  with how much this edit really enlarges it.

It never blocks. Relay the note to the user in their words: which recording,
by how much, and that the fix is the original file. Do not present the
correction below as a substitute for it.

## `picture_policy`

In the project config, compiled into the brand contract:

- `measured` — the default. Measure, then apply only what the measurement
  justifies.
- `none` — the picture is rendered exactly as recorded, and nothing is measured.
- `required` — a recording that cannot be measured, or a correction this
  ffmpeg cannot draw, stops the render instead of leaving the picture alone.

`render --no-picture-correction` renders one file as recorded without editing
the contract. Delivery renders its variants the way the approved final was
rendered.

## What is measured and what can be applied

Measured on a few frames of each recording, spread over the parts of it the
edit uses, inside the crop the edit shows and over its upper two thirds (where
the speaker is; the rest is hands, a table and captions): the median
brightness and its 5th and 95th percentile, the colour balance of near-neutral
pixels, how much the edit enlarges the recording against the final canvas, and
its bits per pixel.

| Measured | Applied | Ceiling |
| --- | --- | --- |
| median brightness under 105 of 255 | lift (`eq` gamma) toward 120, or toward the well-lit recordings of the same edit, up to 140 | gamma 1.35 |
| a lift, or a spread under 105 | contrast, to give back what the lift flattened | 1.10 |
| enlarged 1.15x or more | sharpening after the scale (`unsharp`), by how much it is enlarged | 0.8 |
| under 0.05 bits per pixel | a light denoise (`hqdn3d`) before anything else | fixed, never scaled up |
| a colour cast | nothing | reported, never corrected |

A cast is only reported because a room with green walls measures the same as a
wrong white balance, and guessing the light a scene was shot in is invention.
A well-lit recording is never darkened to match a dark one.

The corrections run on the recording's own pixels, before the reframe; the
sharpening runs after the scale and before any padding; a creative `grade`
comes after both.

## What to tell the user

Every render says what it changed, per recording, and how to undo it:

```text
picture was changed by measured correction:
  - wieczor: dark picture lifted from 92 to about 118; enlarged 1.6x, sharpened
  to undo: re-render with --no-picture-correction, or set picture_policy: none
```

Say it in those terms. Never call it enhancement or colour grading, and never
promise it makes a small file sharp. When a lift stops at its ceiling the
recording is still darker than the others: that is the honest result, and the
remedy is light at the shoot.

The render manifest records the policy, each recording's measurement, the
steps applied and skipped and the ceilings in force (`picture_policy`,
`picture_applied`). Brand QA checks that evidence: the policy the contract
asked for, a measurement behind every correction, every step inside its
ceiling, and that the change is disclosed.
