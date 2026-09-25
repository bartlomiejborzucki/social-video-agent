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

## Workflow (Stage 2)

1. Compile the EDL, then `social-video-agent motion suggest SOURCE -w WORKSPACE`.
   It lists accents found in what is said: the **hook** (first sentence as a
   hook card), **figures** (a counting stat), **enumerations** (numbered steps),
   **questions** (a callout), **punchlines** (a push-in after a pause),
   **turns** ("ale", "zamiast", "but": a push-in) and **jumping cuts** (a
   transition). Each has an id and a confidence, spaced to the energy level;
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

Always accept or write a hook card unless the first frame already carries the
hook. It is where a scrolling viewer decides.

## Vocabulary

| Type | Use for | Needs |
|---|---|---|
| `hook_card` | the opening line, full frame, first 0.5 s | `text` ≤ 90 chars |
| `stat` | one figure worth seeing | `text` ≤ 12 chars, `secondary_text` label |
| `chart` | figures compared | 2–6 `items` "Label: number" |
| `compare` | before/after, us/them | 2 `items` "Label: text" |
| `steps` / `list` | a process / points | 2–5 `items` |
| `quote` | a line worth keeping | `text`, `secondary_text` attribution |
| `callout` | a question, a key claim | `text` |
| `chapter` | a new part of the argument | `text`, `secondary_text` kicker |
| `cta` | the one action at the end | `text` |
| `lower_third` | who is speaking | `text`, `secondary_text` role |
| `progress`, `logo_reveal`, `end_card`, `hook` | as named | see artifacts.md |

`transitions` (`zoom`, `slide`, `flash`) sit on cuts only. `punch_ins` push the
picture only; captions and graphics stay put.

## Style

`style_pack` in the project config picks the visual family — `editorial`
(cards with an accent edge), `bold-social` (accent-filled cards, uppercase,
pop entrances), `tech-minimal` (sharp corners, slide entrances) — always in the
brand's colours and font. Do not mix packs within one video.

## Review (Stage 3)

`social-video-agent motion sheet -w WORKSPACE` writes `qa/motion-sheet.png`,
one labelled frame per graphic, punch-in and transition. Judge each: does it
land on the words it serves, is it readable in its time on screen, does it
cover a face or the captions? `motion variants -w WORKSPACE --text "..."
--text "..."` renders one preview per hook line, for the user to test.
