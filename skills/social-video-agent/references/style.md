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
- `background_style`: `none`, `box`, `rounded_box` (one box around the cue), or
  `rounded_lines` (one rounded box per line, joined where the lines meet, as
  on TikTok). `rounded_lines` is drawn by Remotion only; the FFmpeg route
  refuses a contract that asks for it.
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
- `emphasis_mark: highlight | underline | circle` draws a hand-made mark on
  each emphasis word as it is spoken (from the cue start without word timings).
  Remotion only; the FFmpeg route refuses it, and brand QA fails a render that
  did not draw it. A highlighted keyword keeps the caption colour, so the
  marker in `emphasis_color` does not hide it.

- `upcoming_word_opacity` (0.3–1.0, default 1.0 = as before) draws the
  words of the caption on screen that are not spoken yet at that opacity: the
  said words stay full, the spoken one takes the highlight, the rest wait,
  dimmed. It works with `active_word_highlight`, `emphasis_mark` and
  `rounded_lines`. Remotion only; the FFmpeg route refuses it, and brand QA
  fails a render that did not draw it. It needs word timings.

Captions are never truncated to fit. Layout is measured against the project
font in Python and handed to Remotion as explicit lines, so nothing is wrapped
or clamped in the browser. A cue that does not fit is wrapped, then shrunk to
at most 72% of the contracted size, then refused with its text named. Brand QA
checks what was drawn: lost text, an added ellipsis, a line wider than the box,
a cue longer than the contract, or a style that does not match the contract.
`config validate` refuses a caption geometry whose own text cannot be drawn at
the configured resolution.

## Motion energy and style packs

`motion_energy: calm | lively | bold` in the project config sets, at once, the
largest punch-in, how many transitions are allowed, how many accents `motion
suggest` proposes and how the spoken word animates. `style_pack: editorial |
bold-social | tech-minimal` sets the look of every graphic, in the brand's
colours and font. `caption_style.animation: pop | box` overrides the word
animation (Remotion draws it; the FFmpeg route draws a colour highlight and
brand QA warns). See [motion-design.md](motion-design.md). To match a
reference video, `style analyze` measures its rhythm; `--editorial` prepares
stills and its timed transcript for a read of how it tells the story
([reference-analysis.md](reference-analysis.md)).

## The icon dictionary

`icon_dictionary` in the project config names a YAML file (relative to the
project root) that maps spoken words to icons, with the other words that say
the same:

```yaml
icons:
  kąpiel: bath
  bajka: book
synonyms:
  kąpiel: [wanna]
```

`motion suggest` proposes an `icon` only for a word listed here, with Polish
endings handled ("kąpieli", "bajkę", "wannie"). The names are Tabler Icons
outline icons (https://tabler.io/icons); an unknown name is refused when the
reel is rendered.

## Captions

Generated from word timings and mapped onto the *output* timeline, so they stay
in sync no matter how much is cut. A word straddling a cut is kept only for the
part that survives.

Active-word highlighting is drawn by both renderers: libass with `\k` timing,
Remotion with per-word spans. Either way it needs word timings in the caption
data, and brand QA fails when the contract asks for it and the renderer did not
draw it.

A phrase cue never ends on a word that belongs to what follows it -- a
preposition, a conjunction, a negation (`leaning` in
`captions/data/phrases.yaml`): when a limit closes the cue there, that word
opens the next one instead ("...razem" / "do parku"). A word with a comma or
a full stop after it stays where the speaker stopped. `reel-check` reports
cues that stop mid-phrase as "captions end on whole phrases".

`caption_style.mode: phrase` cuts cues where the sentence breaks instead of
by word count: 3 to `max_words_per_cue` words (6 suits it), ending at any
comma or sentence mark and before a conjunction (`i`, `ale`, `bo`, `że`,
`który`...; the lists are in `captions/data/phrases.yaml`), each on screen at
most 2.5 s, never lit word by word (`active_word_highlight` and
`upcoming_word_opacity` are refused with it). `outline_width_pct` sets the
outline as a share of the font size, drawn outside the glyph; `step_numbers`
puts "1." / "2." in front of a cue that starts a step ("po pierwsze", "krok
2"), in the caption only. Brand QA checks the track was built in the
contracted mode. A test variant beside the house style:

```yaml
caption_style:
  mode: phrase
  case: upper
  max_words_per_cue: 6
  max_chars_per_cue: 28
  outline_or_shadow: outline
  outline_width_pct: 8
  background_style: none
  step_numbers: true
```

The `punchy-caps` brand profile is the same look for an edit without a
project config. Colours stay the brand's; which variant wins is decided from
the published reels' numbers, not by the tool.

`title_font` (or `title_font_file`) is the font of the `hook_title` and the
`end_teaser`, apart from the captions' `font`.

Unicode works: Polish, German, French, Cyrillic are checked against the font
before rendering. If the chosen font lacks glyphs, `doctor` says so rather than
letting it render as empty boxes.

### Captions in another language

Translation is yours; the CLI never calls a translation service, and nothing is
dubbed. After the captions are final:

```bash
social-video-agent captions translate -w WORKSPACE --to en
# fill in every "translation" in captions/<edl>.translate-en.json
social-video-agent captions apply -w WORKSPACE --to en [--max-chars 42]
social-video-agent deliver WORKSPACE --output DEST --language en --srt
```

Translate meaning, not word for word, within `max_chars_per_cue` (or a
per-language `--max-chars`). `apply` refuses a file that adds, drops or retimes
a cue, leaves one empty, or runs over the limit. The translated track keeps the
original timings; its word timings are estimated across each cue, so the
active-word highlight follows them only approximately. Say so to the user.

## Vertical framing

`--reframe` or the profile's default:

- `fit` — no crop, pad the remainder. Never loses content. Use when the framing
  matters more than filling the screen.
- `center` — fixed centre crop. Predictable, needs no model.
- `face` — crop follows detected faces. The usual choice for talking heads.
  The detection model ships with the package, so it works in a session that
  cannot reach the network; `doctor` reports it as `face model`.
- `speaker` — for two-person conversations. Tracks each face across sampled
  frames, measures mouth movement, and correlates it with the speech envelope;
  the face that moves when the audio is loud gets the crop. This is a
  correlation heuristic, not neural active-speaker detection: when no face is
  convincingly ahead of the runner-up it says so in the reframe reason and falls
  back to face prominence rather than following the wrong person silently.

Where the crop has room vertically, the speaker's eyes go on the upper third
(30 % of the frame height from the top), from the eye landmarks the detector
returns. Each face-framed range records where the eyes are and how tall the
face is (`reframe.focus_x`, `focus_y`, `face_height`, and in its `reason`),
including a recording shown whole. A range's `zoom` pushes in on that point,
so a punch-in goes toward the face and the eyes stay where they were on
screen; without a measured face it pushes in on the centre, as before. QA
warns under "framing between ranges" when, across a cut, faces differ in size
by more than 1.35x or eye lines by more than 8 % of the frame height, and
names the `zoom` that evens the sizes. It compares each range with the next
one, not the extremes of the edit, and a different `zoom` on two ranges of
one recording (the punch that hides a jump cut) is not counted. A recording
shown whole has no picture above the frame, so eyes that sit too high stay a
warning: leave room above the head when recording.

The crop is deliberately lazy. It holds still inside a dead zone, moves
gradually when it moves, and only jumps at a scene cut. If the result looks
nervous, raise the dead zone rather than disabling tracking.

Framing is recorded in the EDL as a crop size plus keyframes with a stated
reason, so you can inspect and override it.

For a conversation, transcribe with `--diarize` (the `diarize` extra and the
user's own `HF_TOKEN`; tell them the weights are gated and that audio stays
local). Words then carry `S1`, `S2`… labels, captions break on speaker change,
and `speaker` reframing follows whoever holds the floor, cutting between faces
at turn changes and ignoring interjections under a second. When speakers
cannot be matched to faces it says so and frames one person.

`split_stack` stacks two or three regions of the source as horizontal bands,
listed top to bottom in the range's `reframe.panes`: each pane is a source
rectangle (`x`, `y`, `width`, `height`), a `share` of the output height (shares
add up to 1), and a `fit` — `cover` for a face, `contain` for a screen share,
where cropping would cut off text. With `split_stack` as the default reframe,
the reframe stage proposes one pane per person when two people are in shot
often enough, and says why and falls back to a centre crop when they are not.
A screen above the presenter is written by hand: screen region `contain` at
about `0.6`, face region `cover` at `0.4`. Choose it per range; a whole
interview in split screen is as tiring as one never in it.

## Punch-ins

`punch_in_words` in the config lists words that earn a push in when said
("ważne", "zapamiętaj"); `motion suggest` proposes one on each (1.10-1.18,
anchored with `at_word`) and `motion qa` notes one said without.

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
