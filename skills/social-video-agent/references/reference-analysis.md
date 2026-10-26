# Editorial read of a reference video

A transcript alone does not say how a video holds attention. What the viewer
sees first, what is only written on screen, when the thing being talked about
appears and how the video ends matter as much. You read that from stills and
the timed transcript in your own session; the CLI only prepares the material
and checks the read. No model API is called.

Use a reference only when the user supplies the file or it was fetched with
`fetch --rights`. Never fetch someone else's video yourself.

## 1. Prepare the material

```bash
social-video-agent style analyze REFERENCE -w WORKSPACE --editorial --transcribe
```

Besides `context/style-reference.json` (rhythm, see
[motion-design.md](motion-design.md)), this writes under `context/reference/`:

- `frames/f000-0000.00s.jpg …`: the first frame, a still every 0.5 s through
  the first 3 s, a still just after each detected cut, the middle of each shot
  and the last frame (`--frames` caps the count, default 40);
- `transcript.json`: the reference's timed transcript, kept out of the
  project's packed transcript;
- `material.json`: the still index (id, time, reason), measures (first cut,
  end of the first sentence, longest pauses, cut times) and `limitations`.

## 2. Read it and write `context/reference-analysis.json`

Open the stills (at least every `first`, `opening` and `cut` one) and the
transcript. Write one section per question:

| section | question |
|---|---|
| `opening_attention` | what stops the viewer in the first seconds |
| `said_vs_written` | what is said aloud and what is only written on screen |
| `promise` | what the video promises |
| `development` | how it develops the topic |
| `payoff` | where it keeps the promise |
| `ending` | how it ends |

Rules:

- An **observation** states what is visible or audible, anchored to `at`
  (seconds) or `frame` (a still id), with `evidence`: `frame`, `transcript` or
  `measure`. No judgement in an observation.
- A **hypothesis** is a guess about why it might work and cites observation
  ids in `based_on`. Never present a hypothesis as a finding.
- A section with nothing to report gets `not_found` with a reason.
- `transferable_pattern`: how the user's own material could be presented this
  way, in their own words and footage.
- `not_to_copy`: the reference's wording, faces, voice, graphics, music.
- `needs_review`: stretches the stills may misread (a quick gesture, a move,
  a reveal between stills) for the user to watch.
- `limitations`: anything you add; the material's own limits are added by the
  check.

```json
{
  "reference_fingerprint": "<from material.json>",
  "opening_attention": {
    "observations": [
      {"id": "o1", "frame": "f000", "evidence": "frame", "text": "Close-up of a hand holding a cup."},
      {"id": "o2", "at": 0.4, "evidence": "transcript", "text": "First words are a question."}
    ],
    "hypotheses": [{"text": "The object makes the topic clear before a word is said.", "based_on": ["o1"]}]
  },
  "said_vs_written": {"not_found": "no on-screen text in any still"},
  "promise": {"observations": [], "not_found": "…"},
  "development": {"observations": []},
  "payoff": {"observations": []},
  "ending": {"observations": []},
  "transferable_pattern": "Open on the object in hand, then ask the question aloud.",
  "not_to_copy": ["the wording", "the presenter's face and voice"],
  "needs_review": [{"start": 1.2, "end": 1.8, "reason": "a gesture between two stills"}]
}
```

### A reference without speech

When the transcript finds no words (`style analyze` prints "no speech found"
and adds it to `limitations`), the video speaks through on-screen text, picture
and sound. Read the text in the stills instead: `said_vs_written` records what
is written and that nothing is said, `promise` and `payoff` come from the
written lines, and the measures have no first sentence. Say what the music or
sound does only where a still or a measure shows it.

## 3. Check it

```bash
social-video-agent style check-analysis -w WORKSPACE
```

It exits 1 when an observation points past the end of the video or at a still
that was not pulled, a hypothesis cites an unknown observation, an id repeats,
or a section is empty without `not_found`. On success it writes
`context/reference-analysis.md` for the user, with every limitation listed.

## Reporting it

Say that the read rests on N stills and the transcript, not on watching the
whole video, and list the `needs_review` stretches. Carry the pattern into the
edit plan as a way of telling the story; do not copy the reference.
