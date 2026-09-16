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
  at 1080p and 4K.
- `margin_pct` defaults to 12%, which clears the platform UI. Reels, Shorts and
  TikTok all overlay the bottom of the frame; captions placed lower get covered.
- `max_words_per_cue` / `max_chars_per_cue` bound each cue; breaks still prefer
  sentence and clause boundaries.
- `case` defaults to as-spoken. Uppercase is a style choice, not a default.

## Captions

Generated from word timings and mapped onto the *output* timeline, so they stay
in sync no matter how much is cut. A word straddling a cut is kept only for the
part that survives.

Unicode works: Polish, German, French, Cyrillic are checked against the font
before rendering. If the chosen font lacks glyphs, `doctor` says so rather than
letting it render as empty boxes.

## Vertical framing

`--reframe` or the profile's default:

- `fit` — no crop, pad the remainder. Never loses content. Use when the framing
  matters more than filling the screen.
- `center` — fixed centre crop. Predictable, needs no model.
- `face` — crop follows detected faces. The usual choice for talking heads.
- `speaker` — for two-person conversations.

The crop is deliberately lazy. It holds still inside a dead zone, moves
gradually when it moves, and only jumps at a scene cut. If the result looks
nervous, raise the dead zone rather than disabling tracking.

Framing is recorded in the EDL as a crop size plus keyframes with a stated
reason, so you can inspect and override it.

## Punch-ins

Off by default. When enabled, a punch-in should mark an editorial moment — a
shift in argument, the arrival of the point. Set `zoom` on the specific range,
typically 1.08 to 1.12. Do not apply them on a timer.
