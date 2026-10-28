# Motion design: rhythm that holds a viewer

A well-cut short that never moves reads as a recording. Motion is how a Reel
earns the second, fifth and fifteenth second of attention. Use it on purpose,
every time, sized to the project's `motion_energy`.

## Rhythm rule

Something changes every 3–5 seconds: a cut, a punch-in, a graphic, a caption
accent, a transition. Nothing changes for its own sake.

| `motion_energy` | Punch-in up to | Transitions | Accents | Caption words |
|---|---|---|---|---|
| `calm` | 1.12 | none | ~4/min | highlight only |
| `lively` | 1.18 | ~4/min | ~10/min | `pop` |
| `bold` | 1.25 | ~8/min | ~16/min | `box` |

`lively` suits most Reels and Shorts. `calm` suits authoritative or sensitive
material. `bold` suits fast social formats. The render refuses movement above
the level's limits.

## Matching a reference ("make it feel like this")

When the user points at a video they want the edit to feel like, and it is a
file they already have, run
`social-video-agent style analyze REFERENCE -w WORKSPACE` (add `--transcribe`
for speaking pace and when the first sentence ends). It measures shot length,
cut rate, pauses and hook timing, writes `context/style-reference.json` and a
contact sheet `context/style-reference.png`, and maps the numbers onto
`motion_energy`, a target shot length and a hook deadline. Never fetch someone
else's video to use as a reference.

- Look at the contact sheet and choose the `style_pack` closest to its look;
  the code does not judge looks.
- Propose the energy and pack to the user as a config change; it is theirs to
  accept. The reference never overrides a project rule or the brand.
- Keep only the rhythm: aim for shots around `target_shot_seconds` and land
  the hook within `hook_within_seconds`. Copy no wording, frame, graphic or
  sound from the reference.
- When no cut was detected, check the contact sheet: jump cuts within one
  framing are invisible to scene detection.
- Name the reference and what you took from it in `motion-plan.json`'s
  `rationale`.
- For how the reference opens, promises and pays off (not only its rhythm),
  add `--editorial` and follow [reference-analysis.md](reference-analysis.md).

## Workflow (Stage 2)

1. Compile the EDL, then `social-video-agent motion suggest SOURCE -w WORKSPACE`.
   It lists accents found in what is said: the **hook** (first sentence as a
   hook card), **figures** (a counting stat), **enumerations** (numbered steps),
   **questions** (a callout), **punchlines** (a push-in after a pause),
   **turns** ("ale", "zamiast", "but": a push-in), **jumping cuts** (a
   transition) and **mid-speech cuts in one take** (a `jump`: a sharp change
   of framing, see below). It also reads what the words mean as they are said:
   **replacements** ("zamiast X powiedz Y", "nie mów X", "lepiej: Y": a
   `strike`), **quotes** ("mówi: …", "mówi, że …", a line the brief puts in
   quotes: a `bubble`), **sequences** ("najpierw… potem… na końcu": a
   `process`) and **words from the icon dictionary** (an `icon`); suggested
   steps and stages come anchored to their words. Each has an id and a
   confidence, spaced to the energy level; over a licensed music bed punch-ins
   land on the beat. `--sensitive` (or `sensitive_topic: true` in the plan)
   leaves the word graphics out.
2. Read each against the transcript and the story. Accept by id
   (`motion accept -w WORKSPACE acc-001 acc-004`) or by kind
   (`--kind stat --kind transition`). Reject what repeats the obvious.
3. Add what the code cannot see: a chart for numbers compared across time,
   a compare card for before/after, a CTA near the end, an end card.
4. Optionally `motion sfx [LIBRARY] -w WORKSPACE`: a whoosh under each
   transition, a pop under each graphic, a hit under the hook card, from a
   folder of effects. Without LIBRARY it uses a small built-in CC0 set (whoosh,
   whip, click from `@remotion/sfx`), downloaded once into the cache and checked
   against pinned hashes. The effects live in `edl.json`: run it after the
   last `compile --force` (which rebuilds the EDL from the plan, so an end
   card's new `hold` reaches `end_hold`, and warns that it dropped them).
   Each scene of an imported Motion film counts as a graphic, so it may run
   before or after `motion film import`. A file quieter than -14 dBFS over its
   loudest 50 ms (the built-in click is about -21) is raised to that level,
   within the +6 dB a sound effect allows, and its `reason` says so; no file
   is turned down.
5. Optionally `broll suggest SOURCE -w WORKSPACE` (the library is
   `broll_library` in the config, or `--library DIR`), then `broll accept`:
   the user's own clips cut in where their subject is said. See below.
6. Optionally, on a Claude host with the Motion type, author full-frame
   graphics (hook card, chapter, CTA, quote, end card) as a Claude Motion film:
   [motion-film.md](motion-film.md).

Under `opening_policy: content_first` (the default) there is no hook card: the
first caption carries the situation from frame 0, and a card over the opening
is what a scrolling viewer leaves on. `motion suggest` then proposes none. With
`opening_policy: free`, accept or write a hook card unless the first frame
already carries the hook. See [opening.md](opening.md).

## Vocabulary

| Type | Use for | Needs |
|---|---|---|
| `hook_card` | the opening line, full frame, first 0.5 s | `text` ≤ 90 chars |
| `stat` | one figure worth seeing | `text` ≤ 12 chars, `secondary_text` label |
| `chart` | figures compared | 2–6 `items` "Label: number" |
| `compare` | before/after, us/them | 2 `items` "Label: text" |
| `steps` / `list` | a process / points | 2–5 `items`; `position` `center` or `top`; `item_at_words` puts each on its word |
| `quote` | a line worth keeping | `text`, `secondary_text` attribution |
| `callout` | a question, a key claim | `text` |
| `chapter` | a new part of the argument | `text`, `secondary_text` kicker |
| `cta` | the one action at the end | `text`; `position` `above_captions` or `top` |
| `lower_third` | who is speaking | `text`, `secondary_text` role |
| `label` | names the scene ("Spróbuj tak"), drawn per `label_style` | `text` that fits the frame tab |
| `sticker` | a reaction on one word: an allowlisted emoji or a project PNG/WebP/SVG | `emoji` or `image_asset`, `at_word`, 0.6–1.5 s |
| `strike` | a habit crossed out and replaced ("Nie płacz!" → "Widzę, że ci smutno.") | `text` and `replacement` ≤ 40, `at_word` (the stroke), `replace_at_word` |
| `bubble` | a line said (`variant: speech`) or a message received (`message`) | `text` ≤ 60, `secondary_text` ≤ 40, `at_word`; top only |
| `icon` | the thing just named, over the head | `icon` (Tabler name), `at_word`, 0.6–1.2 s |
| `process` | stages of a routine as a bar, a pointer, a closing state | 2–5 `items` ≤ 12 chars, `item_at_words`, `text` title, `done_text` |
| `kinetic_word` | one key word built letter by letter | `text`: one word ≤ 12, `at_word`; one per reel, not `calm` |
| `inset` | a picture or clip from the project over the speaker | `image_asset` or `video_asset`, `rights`, `size_pct`, `at_word` |
| `custom` | a sentence no type above can say | `component` (`motion/custom/<id>.tsx`); see below |
| `progress`, `logo_reveal`, `end_card`, `hook` | as named | see artifacts.md |

`shakes` (in the plan, beside `punch_ins`) shake the whole picture for a
moment: `{start, end, amplitude_pct, frequency_hz}`, 0.15–2 s, or anchored
with `at_word`. Both renderers draw them, so the "trzęsący" scene of a script
needs no derivative file; for a whole range use `grade: shake`.

`transitions` (`zoom`, `slide`, `flash`, `light_leak`) sit on cuts only.
`light_leak` is a warm film leak tinted to the accent that covers the whole
frame on the cut: use it between scenes or places, at most once or twice a
reel, never as the default. Never put one on a
cut inside one take while the speaker keeps talking: a zoom or blur over a
mouth that is still moving reads as the sound being out of sync. For a cut
with speech on both sides (at most 0.3 s of silence) `motion suggest`
proposes a `jump` instead -- the range after the cut framed at 1.1 (inside
1.08–1.12), fully sharp, on the cut. `motion accept` writes that `zoom` onto
the plan item and the EDL range, so it survives a recompile. `motion qa`
warns about any transition that still runs over speech with a face on screen.
Prefer `zoom`; a
`slide` scales the picture just enough to keep the frame covered while it
moves, so it never shows a black edge, but it is the busiest of the three.
`punch_ins` push the picture only; captions and graphics stay put.

## Labels, the call to action and lists

A label names a scene. It must never look like a caption, or the viewer reads
the scene name as something said. The project's `label_style` decides how it
is drawn, on both renderers:

- `chip` (default): a pill in the top safe zone, white with text in the brand's
  second colour and an accent dot -- the second colour with white text when the
  captions themselves sit on white. Never the caption box colour.
- `scene_frame`: the label is the title tab of a frame drawn around the caption
  band for as long as the label lasts, and the captions inside it are centred
  in the frame. The frame keeps one geometry for the whole scene. When the next
  label starts where this one ends (within 0.05 s), the frame stays, the title
  flips over in about half a second and the rim flashes the accent colour. Set
  `caption_hold_through_pauses: true` with it, so a pause never leaves the
  frame empty. The FFmpeg route draws the same frame around rounded-box
  captions; with another caption background it draws no labels and says so.

A title is fitted to its tab, measured with the brand font: it keeps the
frame's size when it fits, shrinks (at most to 60 %) when it does not, and is
refused with the length that would fit when even that is not enough -- the
limit is the frame's width, not a number of characters. `motion qa` reports
each title's size.

The tab, a top list card and the CTA text use `secondary_color` (default: the
second `brand_colors` entry); the dot, flash and CTA rim use the accent. Every
size is a share of the output height, so a 720x1280 preview is the final,
scaled.

`compile` pins labels to the scenes the edit made: a label whose text is a
plan item's `beat` spans exactly that item's ranges; any other label edge moves
to the nearest cut within 1.5 s, and labels that then nearly meet are joined so
the title flips instead of the frame leaving. It prints every label it moved.
Two rows of one label that meet (a brief that splits a scene in two) become
one label; two different labels on one scene are refused before `edl.json`
is written, so a failed compile leaves the previous edit as it was.

A `cta` sits above the caption band by default. Inside a scene frame that
crowds the rim, and `motion qa` says so; use `position: top` -- a white pill,
text in the second colour, an accent bookmark and a gentle pulse. A `list` or
`steps` sits in the middle by default, which covers a face in a talking-head
shot; `position: top` puts it over the upper zone as a card in the second
colour. `motion qa` measures both where they are actually drawn.

## The end card

An `end_card` is the last thing on screen. Its text is laid out in Python
with the brand font and drawn as given: a link, domain or e-mail address
(`przyklad-marki.example/strona-z-zapisami/`) is never split, the font shrinks
until the longest one fits the width, and `\n` starts a new line. An element
that reaches the final frame never fades out over it.

- `hold: true` places the card after the last word and extends the edit by its
  length (`end - start`) in silence: `edl.json` gets `end_hold`, the base
  render holds its last frame, and the card covers it to the end. `compile`
  and the render keep the two in step; QA approves that still tail.
- Several held cards follow one another after the last word, in the order of
  their `start` (an explanation, then the call to action), up to 10 s in all.
  Each keeps its length; an earlier card stays whole under the next one while
  it enters, so the picture never shows between them, and only the last runs
  to the final frame.
- `layout: image_top` draws the `image_asset` whole in the upper half (a book
  cover) and the text below it; the default `overlay` dims the image behind
  the text.

```json
{"type": "end_card", "start": 0, "end": 2.6, "hold": true,
 "text": "Nowy poradnik\nZapisz się na listę\nprzyklad-marki.example/strona-z-zapisami/",
 "secondary_text": "Premiera: wkrótce\nlink także w bio",
 "reason": "The waiting-list link after the last word."}
```

## Stickers and the shake on a word

The script says "w 0:07, na „Zgodziłeś!”, emotikona wstrząsu i obraz się
trzęsie". That is one sticker and one shake, both on the word:

```json
"elements": [{"type": "sticker", "start": 0, "end": 0.9, "emoji": "😳",
  "at_word": "Zgodziłeś!", "occurrence": 1, "animation": "shake",
  "size_pct": 11, "x_pct": 0.8, "y_pct": 0.3, "reason": "Shock at the promise."}],
"shakes": [{"start": 0, "end": 0.4, "amplitude_pct": 1.2, "frequency_hz": 9,
  "at_word": "Zgodziłeś!", "reason": "The parent's promise hits."}]
```

- `at_word` with `occurrence` (1 = the first time it is said) places it on the
  caption word; `compile` and the render move it there and print the move. A
  word the captions do not hold is an error.
- `animation`: `pop`, `shake`, `pulse` or `drop`; 0.6–1.5 s on screen;
  `size_pct` is the height as a share of the frame; `x_pct`/`y_pct` its centre.
- The brand decides what may appear: an emoji only from `sticker_allowlist` in
  the project config, drawn only from Noto Color Emoji (SIL OFL, commercial use
  allowed; the font, licence and source are recorded in the render manifest as
  `stickers_applied`); or a small image from the project. At most 0 (`calm`),
  1 (`lively`) or 2 (`bold`) per reel; never in the opening frame (from 0.3 s),
  never on the end card or a hook card.
- `animated_emoji: true` plays the emoji's Noto Animated Emoji clip (a laughing
  face that laughs) instead of the still glyph; it reads as livelier and is the
  better choice for a reaction. The clip is downloaded once into the cache.
  It is CC BY 4.0: the manifest's `stickers_applied` carries a `credit`, and
  that credit goes in the post description (see publishing.md). An emoji with
  no animated version is refused with its name.
- Place it in the safe zone off the face, the caption band and the scene frame:
  `motion qa` measures each sticker against faces (box overlap), the captions
  while one is up, and the frame, plus its time on screen.

## Graphics on the word

A reel that holds attention illustrates what is said at the moment it is
said: an icon on the noun, a bubble on the quote, each point of a list on its
word, a habit crossed out on the word that replaces it. That is a different
thing from more motion: the energy's accent budget is unchanged and every word
graphic counts as one accent, like any other graphic.

**Where things sit.** Graphics go in the **top zone, over the head**; the
captions sit at **chest height** (the lower safe zone); **the face stays
free**. Every word graphic is drawn in the top zone unless the plan puts a
`strike`, `inset` or `custom` element at `position: center`, and `motion qa` measures it against faces, the
caption band and the scene frame where it is actually drawn.

**Anchored to the word.** `at_word` + `occurrence` sets a `bubble`, `icon`,
`kinetic_word`, `inset` or `custom` element's start, as for a sticker. A
`strike`'s `at_word` is the moment of the stroke and `replace_at_word` the
moment the replacement enters. `item_at_words` (one entry per item, a word or
`{word, occurrence}`) enters each point of a `list`, `steps` or `process` on
its word; without it the items are revealed evenly, as before. `compile` and
the render move every anchor to its caption word and print each move; a word
the captions do not hold is an error. A list or strike stays until its last
line has been read, but never past the end of the edit.

```json
{"type": "list", "start": 3.0, "end": 9.0, "text": "Spróbuj tak",
 "items": ["Kąpiel", "Bajka"], "item_at_words": ["kąpiel", {"word": "bajka", "occurrence": 2}],
 "position": "top", "reason": "Each point as it is said."},
{"type": "strike", "start": 10.0, "end": 15.0, "text": "Nie płacz!",
 "replacement": "Widzę, że ci smutno.", "at_word": "zamiast", "replace_at_word": "widzę",
 "strike_mark": "cross", "reason": "The habit, crossed out."},
{"type": "bubble", "start": 1.0, "end": 3.0, "variant": "message",
 "text": "Co robić, gdy dziecko krzyczy?", "secondary_text": "pytanie od obserwatorki",
 "at_word": "krzyczy", "reason": "The question this Q&A answers."}
```

- **`strike`**: the line appears, a stroke in the accent crosses it out on its
  word (`strike_mark`: `scissors` or `cross` adds a mark), then `replacement`
  takes its place. 1.5–10 s; `position` `top` (default) or `center`.
- **`bubble`**: `variant: speech` has a tail at the speaker (`tail:
  speaker`) or out of the frame (`left`, `right`); `message` has a
  notification dot. It pops in with a sound from `motion sfx`. Never a card
  over the shot, never in the opening frame (from 0.3 s), and it never stands
  in for the situation's first caption. No names or logins in
  `secondary_text`.
- **`icon`**: a flat icon from Tabler Icons (MIT), downloaded once into the
  cache at a pinned version and hash; the manifest's `icons_applied` records
  set, version, licence, source and hash. `motion suggest` proposes one only
  for a word in the project's `icon_dictionary` (style.md). At most 0 (`calm`),
  2 (`lively`) or 4 (`bold`) per reel, counted apart from stickers.
- **`process`**: 2–5 stages in the brand colours (never the card's own),
  each entering on its word; a pointer runs through them and `done_text`
  closes it with a tick ("✓ gotowe do snu"). Top only.
- **`kinetic_word`**: one word assembled letter by letter with sparks in the
  brand colours. At most one per reel, none at `calm`.
- **`inset`**: a picture or a short clip (`source_start`/`source_end`, muted)
  from the project — a comment's screenshot, a book page, an earlier reel — as
  a card with rounded corners (`corner_radius`) and a soft shadow, `size_pct`
  of the width (30–90), its height from the picture, capped at 42 % of the
  frame. It needs `rights` and never shows a child's face, as for b-roll;
  `motion qa` warns when it covers a talking mouth for more than 2 s.

**Sensitive subjects.** For a reel about death, illness or grief set
`sensitive_topic: true` in `motion-plan.json`: the plan then refuses every
playful graphic (sticker, strike, bubble, icon, process, kinetic word, inset,
custom) and `motion suggest` proposes none. Points on their words and dimmed
caption words (`upcoming_word_opacity`) stay allowed.

## A component written for one sentence (`custom`)

When no type of the vocabulary says what a sentence means, write the
animation for it. This is the exception, not the default: try the table
first, and keep it to one or two in a reel.

```bash
social-video-agent motion custom init evening-clock -w WORKSPACE   # writes the template
# edit motion/custom/evening-clock.tsx, add the element to motion-plan.json:
#   {"type": "custom", "start": 6.2, "end": 8.4, "component": "evening-clock",
#    "at_word": "wieczór", "reason": "The evening running out, as a clock."}
social-video-agent motion custom check evening-clock -w WORKSPACE  # checks, renders qa/custom-evening-clock.mp4
```

- The component is the file's default export and receives only
  `CustomGraphicProps`: `brand` (accent, secondary, text, background, colors,
  font), `width`/`height` of its zone, the `frame` size, `safeMargins` and the
  `words` said while it is on screen (seconds from its start). Draw only in
  those colours and that font.
- It may import only `react` and these names from `remotion`:
  `AbsoluteFill`, `Easing`, `Freeze`, `Loop`, `Sequence`, `Series`,
  `interpolate`, `interpolateColors`, `measureSpring`, `random`, `spring`,
  `useCurrentFrame`, `useVideoConfig`. No network, no files (`staticFile`,
  `Img`, `Video`), no URLs, no storage, no dynamic import.
- It is clipped to its zone: `position: top` (over the head) or `center`.
  `motion qa` measures that zone against faces and captions, and it counts as
  an accent.
- Every render checks it again (imports, forbidden calls, `tsc --noEmit`
  against the props). A component that fails is left out with the reason
  (`custom_rejected` in the render manifest); the rest of the reel renders.
- Remotion's own agent skills are a good reference for the API: install them
  in your session (`npx skills add remotion-dev/skills`), never into this
  repository.

## Colours and font come from the brand

The motion plan's `accent_color`, `text_color`, `background_color`,
`font_family` and `style` are drafts: a render with a brand contract replaces
them with the contract's values and logs one INFO line per value it replaced,
so brand QA vouches for what was drawn. Change the brand in the project config,
not in the plan. There is no per-element colour override, for the same reason.

## The project's b-roll library

Keep short clips (2–6 s, vertical 9:16, no child's face) in one project folder,
set `broll_library: assets/broll` and `broll_density` (the largest share of
the edit b-roll may cover, e.g. 0.2), and describe every clip in
`broll.yaml` beside them:

```yaml
clips:
  - file: hustawka.mp4
    description: pusta huśtawka w ruchu, park jesienią
    keywords: [park, huśtawka, wyjście]
    child_face_visible: false
    rights: własne nagranie 2026-10, bez osób
```

`broll suggest` matches the transcript's words against the keywords, file
names and `broll_synonyms` from the config (`{park: [huśtawka, ławka]}`),
with Polish endings handled ("parku" finds `park`). A clip with
`child_face_visible: true` is never proposed and is listed as skipped. Over a
speaker talking to the camera a clip stays at most 2 s, so the mouth is not
hidden for long; clips keep at least 3 s apart, so the picture changes every
3–5 s. To ask for b-roll in a reel's brief, name the subject in "Ujęcie"
("wstawka: dłonie przy zapinaniu kurtki") and add the clip with those
keywords to the library.

## Style

`style_pack` in the project config picks the visual family — `editorial`
(cards with an accent edge), `bold-social` (accent-filled cards, uppercase,
pop entrances), `tech-minimal` (sharp corners, slide entrances) — always in the
brand's colours and font. Do not mix packs within one video.

## Review (Stage 3)

`social-video-agent motion qa -w WORKSPACE` measures every graphic first:
time to read it, the caption band and faces it covers, accents per minute and
the longest still stretch. `social-video-agent motion sheet -w WORKSPACE`
then writes `qa/motion-sheet.png`, one labelled frame per graphic, punch-in
and transition, coloured by what `motion qa` found. Judge each: does it
land on the words it serves, is it readable in its time on screen, does it
cover a face or the captions? `motion variants -w WORKSPACE --text "..."
--text "..."` renders one preview per hook line, for the user to test.
