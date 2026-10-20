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

## Workflow (Stage 2)

1. Compile the EDL, then `social-video-agent motion suggest SOURCE -w WORKSPACE`.
   It lists accents found in what is said: the **hook** (first sentence as a
   hook card), **figures** (a counting stat), **enumerations** (numbered steps),
   **questions** (a callout), **punchlines** (a push-in after a pause),
   **turns** ("ale", "zamiast", "but": a push-in), **jumping cuts** (a
   transition) and **mid-speech cuts in one take** (a `jump`: a sharp change
   of framing, see below). Each has an id and a confidence, spaced to the energy level;
   over a licensed music bed punch-ins land on the beat.
2. Read each against the transcript and the story. Accept by id
   (`motion accept -w WORKSPACE acc-001 acc-004`) or by kind
   (`--kind stat --kind transition`). Reject what repeats the obvious.
3. Add what the code cannot see: a chart for numbers compared across time,
   a compare card for before/after, a CTA near the end, an end card.
4. Optionally `motion sfx LIBRARY -w WORKSPACE --licensed`: a whoosh under each
   transition, a pop under each graphic, a hit under the hook card, from the
   user's own licensed effects.
5. Optionally `broll suggest SOURCE --library DIR -w WORKSPACE`, then
   `broll accept`: the user's own clips cut in where their subject is said.
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
| `steps` / `list` | a process / points | 2–5 `items`; `position` `center` or `top` |
| `quote` | a line worth keeping | `text`, `secondary_text` attribution |
| `callout` | a question, a key claim | `text` |
| `chapter` | a new part of the argument | `text`, `secondary_text` kicker |
| `cta` | the one action at the end | `text`; `position` `above_captions` or `top` |
| `lower_third` | who is speaking | `text`, `secondary_text` role |
| `label` | names the scene ("Spróbuj tak"), drawn per `label_style` | `text` that fits the frame tab |
| `progress`, `logo_reveal`, `end_card`, `hook` | as named | see artifacts.md |

`transitions` (`zoom`, `slide`, `flash`) sit on cuts only. Never put one on a
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
- `layout: image_top` draws the `image_asset` whole in the upper half (a book
  cover) and the text below it; the default `overlay` dims the image behind
  the text.

```json
{"type": "end_card", "start": 0, "end": 2.6, "hold": true,
 "text": "Nowy poradnik\nZapisz się na listę\nprzyklad-marki.example/strona-z-zapisami/",
 "secondary_text": "Premiera: wkrótce\nlink także w bio",
 "reason": "The waiting-list link after the last word."}
```

## Colours and font come from the brand

The motion plan's `accent_color`, `text_color`, `background_color`,
`font_family` and `style` are drafts: a render with a brand contract replaces
them with the contract's values and logs one INFO line per value it replaced,
so brand QA vouches for what was drawn. Change the brand in the project config,
not in the plan. There is no per-element colour override, for the same reason.

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
