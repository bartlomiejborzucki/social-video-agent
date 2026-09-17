---
name: social-video-agent
description: Edit video into social clips (Reels, Shorts, TikTok) by reasoning over a transcript and writing an explicit edit plan and EDL that local tools render. Use when the user asks to edit, cut, trim, or clean up a recording, make a Reel or Short, remove mistakes or filler, add captions, or convert horizontal footage to vertical. Do not use for generating video from scratch or for simple one-off format conversions.
license: Apache-2.0
metadata:
  version: "0.1.0"
---

# Editing social video

You are the editor. You decide what the piece is about, what to cut, and where
it opens and closes. The tools handle media mechanics deterministically; they
make no editorial judgements.

## How this works

```
source → transcribe → packed transcript → YOUR editorial decisions
       → edit-plan.json → edl.json → render → technical QA
       → qa-editorial.json → apply only approved fixes → final.mp4
```

Every decision you make is written to an artifact a human can read and change.
Source files are never modified. Linux sources default to `edit/` beside the
source. Sources on `/mnt/<drive>` use a Linux-cache workspace; report that path
from the CLI and use `--output` when the final file belongs on a Windows drive.

**Read the packed transcript, not the raw JSON.** The packed view is a compact
phrase-level document built for reasoning. The raw token JSON exists for the
tools and will flood your context for no benefit.

## Start here

```bash
social-video-agent doctor                      # once, to confirm the machine is ready
social-video-agent inspect INPUT               # what the source actually is
social-video-agent transcribe INPUT            # local, cached, no API key
social-video-agent pack .                      # the view you reason over
```

On Windows, Codex must run inside WSL2. Accept either `/mnt/c/...` or a pasted
`C:\...` path; the CLI normalizes it safely. Keep the repository, cache, model
files, and intermediates in the Linux filesystem. Never invoke `ffmpeg.exe` or
build a PowerShell/`wsl.exe` bridge.

`transcribe` caches on source content plus options, so re-running is free.
Changing model or language re-transcribes; re-running does not.

## Decide before you cut

Read the packed transcript once, end to end. Then form a view:

- What is this piece actually about? One sentence.
- Which moment is the strongest opening? It is rarely the literal beginning.
- What is the payoff, and does the ending land or trail off?
- Which passages are scaffolding ("so basically what I wanted to say was") that
  can go without losing meaning?
- Where did the speaker restart, misspeak, or repeat themselves?
- Is there a better take of the same point later in the recording?

State your strategy to the user in a few sentences and get agreement before
rendering anything long. Do not silently produce a finished video from an
ambiguous request.

## Build the plan

```bash
social-video-agent plan INPUT --profile talking-head --goal "60s educational Reel"
```

This writes `edit/edit-plan.json` containing only what can be found from timing:
dead air, isolated filler, immediately repeated phrases. **It contains no
judgement about meaning.** That part is yours: edit the file directly.

Each item is an action (`keep`, `drop`, `tighten`, `reorder`), a span, and a
`reason`. Write the reason for a human reader — it is the record of why the
edit is the way it is.

To select specific moments rather than trim a whole recording, replace the
drops with explicit `keep` items; explicit keeps take precedence.

## Compile and render

```bash
social-video-agent edit INPUT --profile talking-head --brand default
```

runs the whole chain. Or drive the stages individually and inspect between
them. Cut boundaries are snapped to word edges automatically — you never need
to compute frame numbers, and you should not try.

Render `--quality preview` while iterating and `final` once. Preview keeps the
same aspect and framing, so what you check is what you ship.

If audio continues after the last privacy-safe moving frame, do not let the
renderer invent a multi-second freeze. Record one explicit ending strategy in
the EDL: a second safe B-roll shot, a later B-roll start, an editorially valid
return shot, an edit-plan-approved sentence trim, a designed end card, or an
intentional hold. A hold must state `freeze_at`, `freeze_duration`, and its
reason. More than the default `max_static_hold` of 0.75 seconds additionally
requires `intentional_hold: true`. If none is appropriate, stop and ask for
more B-roll.

## Check your own work

```bash
social-video-agent qa WORKSPACE
```

Mechanical checks run first: exact video/audio timelines and AAC cadence,
standard CFR, full decoding, clipping, black frames, silence at cuts, caption
placement, and repeated-frame runs in the final ten seconds. They catch things
you cannot see in a single still.

The supervising editor must inspect the final ten seconds, the dense ending
contact sheet, the final five seconds frame by frame (or equivalently densely
sampled), the last frame, and the relationship between the end of motion and
the end of audio. Ask whether the picture remains intentional through the last
second, not only whether the spoken payoff is good. Correct captions, a safe
privacy boundary, and successful decoding do not justify a multi-second dead
frame.

Always write `qa-editorial.json` as exactly one of these contracts:

```json
{"status":"approved","fixes":[]}
```

```json
{"status":"changes_requested","fixes":[{"path":"ranges[2].end","value":4.2,"reason":"..."}]}
```

Apply it with `social-video-agent apply-editorial-qa WORKSPACE`. Approval is a
no-op. Changes apply only the listed paths; the command does not perform a new
editorial analysis and rejects unknown paths or schema fields.

If something is wrong, fix the plan or the EDL and re-render. **Stop after three
attempts** and tell the user what remains wrong rather than looping.

## Default to restraint

In priority order: meaning, clarity, natural rhythm, clean cuts, audio quality,
framing, captions, then everything else.

- Keep the speaker's rhythm. Do not remove every pause; pauses carry meaning.
- Do not produce jump-cut-every-two-seconds editing unless asked.
- No music, sound effects, or punch-ins unless requested or enabled by a profile.
- A punch-in marks an editorial moment. Constant zooming is not a style.

Assume the user wants their recording to sound like them, only tighter.

## Reference

| Topic | File |
|---|---|
| Artifact schemas and how to edit them by hand | [references/artifacts.md](references/artifacts.md) |
| Profiles, brands, captions, and vertical framing | [references/style.md](references/style.md) |
| Long recording to several short clips | [references/shorts.md](references/shorts.md) |
| Troubleshooting and platform notes | [references/troubleshooting.md](references/troubleshooting.md) |

## Do not

- Do not write ffmpeg commands by hand. Everything needed is a CLI command; if
  something is genuinely missing, say so rather than improvising a filter graph.
- Do not modify, move, or re-encode the user's source files.
- Do not paste raw transcript JSON into your context.
- Do not upload media to any service. Transcription is local by default; a cloud
  provider must be explicitly requested, and you must tell the user their media
  is leaving the machine.
- Do not invent timestamps. Take them from the packed transcript.
- Do not accept a Reel because the verbal ending works while the picture is
  visibly frozen. Do not disguise missing footage with automatic zoom, loops,
  random transitions, or synthetic motion.
