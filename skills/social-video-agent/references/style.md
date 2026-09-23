# Profiles, brands, captions, framing

## Output profiles

Editorial posture plus canvas. `social-video-agent profiles` lists them.

| profile | for | posture |
|---|---|---|
| `talking-head` | one person to camera | calm, meaning first |
| `educational` | explaining something | keeps reasoning, trims scaffolding |
| `calm-expert` | authoritative delivery | most restrained; keeps filler and long pauses |
| `podcast-clip` | conversation excerpt | speaker-aware framing |
| `technical-tutorial` | screen or demo led | cuts sparingly; pauses carry meaning |
| `storytelling` | narrative | protects beats |
| `vertical-short` | generic 9:16 | balanced |
| `fast-social` | high-energy | tight; opt in deliberately |
| `landscape-16x9`, `square` | other placements | |

The knobs that matter: `max_pause` (longer than this may be tightened),
`min_pause` (never go below; this is what keeps speech human), `cut_padding`,
`remove_filler`.

Profiles are JSON. To add one, drop a file in the profiles directory — never
write code for a new format.

## Brand profiles

Presentation only; they never influence what is cut. `default`, `bold-caption`
(uppercase, active-word highlight), `minimal`.

Caption settings worth knowing:

- `font_size_pct` is a percentage of output height, so it means the same thing
  at 1080p and 4K. The 9:16 reference is `3.6` (~69 px at 1080x1920). Do not
  raise it without checking that real phrases still fit: 5% is ~96 px, which is
  wider than the frame for most Polish phrases.
- `margin_pct` clears the platform UI; the 9:16 reference is `22`. Reels, Shorts
  and TikTok all overlay the bottom of the frame; captions placed lower get
  covered. `qa --platform` measures this against the destination's estimated
  overlay.
- `max_words_per_cue` (reference `4`) and `max_chars_per_cue` (reference `24`)
  bound each cue; breaks still prefer sentence and clause boundaries. These are
  the first line of defence against overflow: a cue is short because it was
  split, not because it was shortened.
- `outline_or_shadow: none` is the reference on a background box. An outline
  thickens every glyph and costs the line width long words need.
- `case` defaults to as-spoken. Uppercase is a style choice, not a default.
- `active_word_highlight: true` colours the word being spoken, exactly while it
  is spoken, in `highlight_color`. Both renderers draw the same thing.
- `emphasis_words` lists brand keywords drawn in `emphasis_color` wherever they
  are spoken. One word per entry, matched ignoring case and edge punctuation;
  inflected forms are separate entries (`Studio` does not match `Studia`). Brand
  QA fails a render that was asked for either and did not draw it. Use it for
  a handful of names, not for decoration: a caption where every third word is
  coloured emphasises nothing.

Captions are never truncated to fit. Layout is measured against the project
font in Python and handed to Remotion as explicit lines, so nothing is wrapped
or clamped in the browser. A cue that does not fit is wrapped, then shrunk to
at most 72% of the contracted size, then refused with its text named. Brand QA
checks what was drawn: lost text, an added ellipsis, a line wider than the box,
a cue longer than the contract, or a style that does not match the contract.
`config validate` refuses a caption geometry whose own text cannot be drawn at
the configured resolution.

## Captions

Generated from word timings and mapped onto the *output* timeline, so they stay
in sync no matter how much is cut. A word straddling a cut is kept only for the
part that survives.

Active-word highlighting is drawn by both renderers: libass with `\k` timing,
Remotion with per-word spans. Either way it needs word timings in the caption
data, and brand QA fails when the contract asks for it and the renderer did not
draw it.

Unicode works: Polish, German, French, Cyrillic are checked against the font
before rendering. If the chosen font lacks glyphs, `doctor` says so rather than
letting it render as empty boxes.

## Vertical framing

`--reframe` or the profile's default:

- `fit` — no crop, pad the remainder. Never loses content. Use when the framing
  matters more than filling the screen.
- `center` — fixed centre crop. Predictable, needs no model.
- `face` — crop follows detected faces. The usual choice for talking heads.
- `speaker` — for two-person conversations. Tracks each face across sampled
  frames, measures mouth movement, and correlates it with the speech envelope;
  the face that moves when the audio is loud gets the crop. This is a
  correlation heuristic, not neural active-speaker detection: when no face is
  convincingly ahead of the runner-up it says so in the reframe reason and falls
  back to face prominence rather than following the wrong person silently.

The crop is deliberately lazy. It holds still inside a dead zone, moves
gradually when it moves, and only jumps at a scene cut. If the result looks
nervous, raise the dead zone rather than disabling tracking.

Framing is recorded in the EDL as a crop size plus keyframes with a stated
reason, so you can inspect and override it.

## Punch-ins

Off by default. When enabled, a punch-in should mark an editorial moment — a
shift in argument, the arrival of the point. Do not apply them on a timer.

Two forms:

- `zoom` on an EDL range holds one scale for the whole range, typically 1.08 to
  1.12. Both renderers draw it.
- A timed push in `motion-plan.json` `punch_ins` (Remotion only): `start`,
  `end`, `scale`, an optional fixed point `focus_x`/`focus_y` (fractions of the
  frame; the default `0.5`/`0.4` sits on a face) and a `reason`. It eases in,
  holds and eases out; captions and graphics do not move. At least 0.4 s long,
  never overlapping.

Rendering refuses any zoom above the brand's `punch_in_max`, and any punch-in
when the project sets `punch_in_intensity: 0`.
