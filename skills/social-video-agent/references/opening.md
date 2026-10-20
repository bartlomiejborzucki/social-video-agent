# Content first: the opening, the cover and the brief

The first second decides whether the rest is watched. In September 2026 the
weakest reels of a parenting brand lost viewers at one second, exactly where a
cover pasted into the timeline cut to the speaker. Their first full caption
arrived at six seconds. The strongest reel opened on the action with the
situation burned in from frame 0. Four files and counters of different ages are
enough to fix the execution, not to prove the cause; check again seven days
after the next reels go out.

## The rule (`opening_policy: content_first`, the default)

- **Frame 0 is the scene.** The person is already in it, or the action has
  begun. No title card, no cover, no logo, no black or white frame at the start.
- **No silence beyond `max_leading_silence_s`** (0.3 s) at the start. Do not
  open on walking up to the phone.
- **The first caption starts at 0.0 s** and carries the whole first sentence
  of the situation, up to `first_cue_max_words` (8) and two lines. This is an
  explicit exception to `max_words_per_cue` and `max_chars_per_cue`. Every
  later cue follows the project's limits.
- **The cover is its own file.** `delivery/cover.jpg` is set on Instagram,
  Facebook, TikTok and YouTube when the reel is published. It never enters the
  timeline. `cover_in_timeline: true` is only allowed with `opening_policy:
  free`.
- **An end card only at the end**, if the project uses one at all. Put it
  after the last word with `hold: true` ([motion-design.md](motion-design.md)):
  the edit is extended by the card's length in silence, so the card never
  covers the last spoken seconds and stays to the final frame. Never cut a
  still image or a silent clip into the plan to make room for it.

The render refuses a content-first edit that opens on a card or ends early on
an end card. Delivery measures the opening and refuses to call a delivery
ready when any rule is broken.

## Configuration

Absent keys take these values, so existing project configs need no change:

```yaml
opening_policy: content_first   # or free: the opening is the editor's call
cover_in_timeline: false        # true only with opening_policy: free
first_cue_full_sentence: true
first_cue_max_words: 8
max_leading_silence_s: 0.3
```

## The brief

A monthly package carries a brief per reel, as text, as an entry of
`plany/pakiet_sm_YYYY-MM.json` (fields `nagranie`, `scenariusz`, `montaz`,
`okladka`), or in the month's posts document in Word
(`PLANY/<MIESIĄC>/posty-RRRR-MM.docx`). It overrides the
project defaults for that edit:

```bash
social-video-agent brief import BRIEF.txt -w WORKSPACE --labels
social-video-agent brief import plany/pakiet_sm_2026-10.json -w WORKSPACE \
  --match "Nie pobawię" --labels
social-video-agent brief import posty-2026-01.docx -w WORKSPACE \
  --match "Przecież się dogadaliśmy" --labels
```

In the Word document each post sits under a heading `DD.MM DZIEŃ · ROLKA ·
Tytuł`; `--match` chooses the reel by its title. Its Nagranie paragraph,
Scenariusz table (Czas | Ujęcie | Co mówisz | Napis na ekranie), Montaż and
Okładka are read; the platform descriptions after them are not. The text is
what Word shows with every tracked change accepted: deletions (`w:del`) are
left out and insertions (`w:ins`) kept, so read the brief from the document
as its author left it, never from a copy with the changes typed in by hand.

- **The first row is the first caption.** The words in "Co mówisz" become cue
  1. When a child says the first line off screen, cue 1 shows the text from
  "Napis na ekranie" instead.
- **A child's voice is never synthesised.** If the recording does not carry
  the child's line, the line is shown as text from 0.0 s until the speech
  begins, and is not heard. When the child's line was recorded on its own
  file, put it under the opening picture with the plan item's
  `audio_source`, `audio_start` and `audio_end`; `compile` captions it from
  that file's transcript.
- **Short texts are labels, not cards.** Texts such as "Częsty odruch" or
  "Spróbuj tak" become `label` graphics that name the scene; `--labels` adds
  them to `motion-plan.json` with the brief's times. They are never drawn like
  a caption: with `label_style: scene_frame` each is the title of a frame around
  that scene's captions, otherwise a chip in the top safe zone
  ([motion-design.md](motion-design.md)). `compile` then pins them to the
  scenes the edit actually made; give a plan item `beat: "Spróbuj tak"` to tie
  a label to its scene exactly.
- **"Okładka" is only for `cover.jpg`:**
  `social-video-agent cover WORKSPACE --from-brief`.
- **The brief goes into the plan.** It is saved as `context/brief.json`, and
  every override is written as a `brief:` line in `edit-plan.json`
  `user_overrides`.

Example, the reel of 13.10.2026 "Nie pobawię się teraz":

```text
Nagranie: Stały kadr z misiem w tle, miętowy detal przy twarzy, kubek „Lubię być mamą” w ręce.
Scenariusz (Czas | Ujęcie | Co mówisz | Napis na ekranie):
- 0–3 s | Pijesz z kubka, słysząc głos dziecka zamykasz oczy | Głos dziecka zza kadru: „Mamo, pobaw się ze mną!” | „Mamo, pobaw się ze mną!” / Jak postawić teraz granicę?
- 3–9 s | Lekko odwracasz głowę do dziecka poza kadrem | „No teraz chyba nie mogę…” | Częsty odruch
- 9–22 s | Cięcie, spokojniejszy głos | „Nie pobawię się teraz. Potrzebuję odpocząć.” | Spróbuj tak
- 22–30 s | Do obiektywu | „Jasna odmowa nie musi być długa…” | Jasna decyzja + miejsce na emocje
Montaż: Pierwsza klatka = scena, nie okładka…
Okładka: NIE POBAWIĘ SIĘ TERAZ. Mały podpis: „Bez kar, czyli jak? / Granice w praktyce”.
```

It gives:
- **First caption:** „Mamo, pobaw się ze mną!” as text only, since the line is a child's off screen.
- **Labels:** "Jak postawić teraz granicę?", "Częsty odruch", "Spróbuj tak" and "Jasna decyzja + miejsce na emocje".
- **Cover:** "NIE POBAWIĘ SIĘ TERAZ" with the subtitle "Bez kar, czyli jak? / Granice w praktyce".

## Checking the opening

```bash
social-video-agent opening-qa WORKSPACE [--first-frame-note "One sentence on frame 0."]
```

It writes `analysis/opening-qa.json`, `analysis/opening-qa.md` and
`analysis/first-frame.png`. Look at the frame and describe it in one sentence;
otherwise the measured description is used. `deliver` runs the same check on
the delivered video and records it in `delivery-manifest.json`:

| Field | Meaning |
|---|---|
| `first_frame_is_content` | Frame 0 is a moving scene, not black, white, flat or held |
| `first_frame_note` | One sentence on what frame 0 shows |
| `first_cue_start_s` | When the first caption appears; must be 0.0 |
| `first_cue_text` | What it says |
| `leading_silence_s` | Silence the audio opens with |
| `cover_in_timeline` | A cover, card or still at the start; must be false |
| `time_to_first_situation_s` | When the first sentence is heard |
| `end_card_only_at_end` | No end card before the end |
| `opening_ready`, `opening_issues` | Whether the delivery is ready, and what to fix |
| `cover_path` | The delivered `cover.jpg` |

When the delivery is not ready, `deliver` exits with the list of fixes and a
proposed variant, and Stage 5 cannot complete. Fix the edit and deliver again.
Without a compiled project contract the fields are recorded but not enforced.
