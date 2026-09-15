# social-video-agent

> Working name. The project is not branded yet; `social-video-agent` is a
> placeholder chosen to be easy to replace.

An **agent-native social video editor**. A coding agent — Claude Code, Codex, or
any Agent Skills-compatible host — acts as the editor: it understands the
recording through a compact transcript, makes explicit editorial decisions,
writes them down as artifacts you can read and change, and lets deterministic
local tools do the media work. Then it checks its own output.

This is not "an LLM writes FFmpeg commands."

```
source → transcribe → packed transcript → editorial decisions
       → edit-plan.json → edl.json → render → QA → revise → final.mp4
```

You should not need Premiere, Final Cut, or CapCut to turn a recording into a
Reel. You should also not need an API key.

## What it does today

Open a folder with a recording in it, start your agent, and say:

> Turn this into a 45-second educational Reel. Keep the editing calm, remove the
> mistakes and repeated explanations, add readable captions.

The agent transcribes locally, reads the transcript, proposes a strategy, and
produces `edit/final.mp4` along with every intermediate artifact.

- **Local transcription** with faster-whisper. No account, no API key, nothing
  uploaded. Real word-level timestamps, so cuts land on word boundaries.
- **Vertical 9:16** from horizontal footage, with face-aware framing that holds
  still rather than drifting around.
- **Captions** as data until the final render, burned in as ASS. Polish,
  German, French and Cyrillic verified against the font before rendering.
- **Mechanical QA**: duration against the EDL, clipping, black frames, silence
  at cut boundaries, caption placement — then targeted stills, not frame-by-frame.
- **Everything inspectable.** The plan, the EDL, the captions and the QA report
  are all readable JSON you can edit by hand and re-render.
- **Your sources are never touched.**

## Relationship to video-use

This project starts from [browser-use/video-use](https://github.com/browser-use/video-use)
(MIT), and the architecture is theirs: transcript-first reasoning, an explicit
EDL, immutable sources, self-evaluation of the rendered result. We did not
invent that and do not claim to have.

What changed is what runs inside it. Upstream requires a paid transcription API
and has declined local transcription six times; it has no cropping code at all,
so it cannot produce 9:16; its cache is a filename check that cannot detect a
changed source; and every ffmpeg failure discards its own error message. The
full audit is in [docs/research/video-use-audit.md](docs/research/video-use-audit.md),
the decision in [ADR-001](docs/architecture/ADR-001-video-use-relationship.md),
and what was taken from where in [provenance](docs/research/provenance.md).

Attribution is permanent. See [UPSTREAM.md](UPSTREAM.md).

## Why local-first

Your recordings are yours. Probing, transcription, editing, rendering, captions,
scene detection and QA all run on your machine with no network access. Cloud
providers exist as opt-in extras, and when one is enabled the agent is instructed
to tell you your media is leaving the device.

The other reason is cost. The semantic work — understanding the content, judging
which take is better, deciding where to open — is done by the coding agent you
are already paying for. The project is not designed around an `OPENAI_API_KEY` or
an `ANTHROPIC_API_KEY`, and does not call a paid LLM API of its own.

## Requirements

- Python 3.10–3.13
- FFmpeg **with libass** (for captions). `social-video doctor` checks this.
- Optional: an NVIDIA GPU with matching cuBLAS/cuDNN. Transcription falls back
  to CPU automatically if it is missing or mismatched.

## Install

```bash
git clone <this repo> && cd social-video-agent
uv sync                       # or: python -m venv .venv && pip install -e .
uv run social-video doctor
```

No ffmpeg? Install it with your package manager, or:

```bash
uv run social-video doctor --install-ffmpeg    # static build, no sudo needed
```

### Make it available to your agent

```bash
python scripts/install_skills.py
```

This links `skills/` into `~/.claude/skills` and `~/.agents/skills`. There is one
canonical skill; Agent Skills is an open standard, so the same folder works in
Claude Code, Codex and other compatible hosts. Restart your agent afterwards.

For Codex plugin installation, this repository is also a plugin: `plugin.json`
(portable) and `.codex-plugin/plugin.json` are both present, as is
`.claude-plugin/marketplace.json` for Claude Code.

## Quick start

```bash
cd ~/footage
social-video inspect talk.mp4        # what the source actually is
social-video transcribe talk.mp4     # local; cached on content + options
social-video pack .                  # the compact view the agent reads
social-video edit talk.mp4 --profile talking-head
```

Then open the folder in your agent and describe what you want. It will use the
same commands, and think in between them.

## Workflows

**Clean up a talking-head recording.** Transcribe, drop dead air and false
starts, cut to vertical, caption, QA. `social-video edit INPUT`.

**Long recording to several shorts.** Transcribe once, find standalone moments,
judge them, refine boundaries, render each with its own framing and captions.
Driven by the agent; see [the shorts reference](skills/social-video-editor/references/shorts.md).

## Editing posture

The default is restrained. In priority order: **meaning, clarity, natural
rhythm, clean cuts, audio quality, framing, captions**, then everything else.

Pauses are part of speech, and removing all of them is what makes automated
edits sound wrong — so profiles tighten long pauses to a floor rather than
closing them. No music, sound effects or punch-ins unless you ask. Captions
default to as-spoken rather than uppercase. You are not assumed to want a
stereotypical TikTok aesthetic.

Ten output profiles ship, from `calm-expert` to `fast-social`
(`social-video profiles`). Profiles and brand styles are JSON configuration, not
code.

## Privacy

Nothing leaves your machine by default. Models are downloaded once on first use
(Whisper from Hugging Face, a 233 KB face-detection model from OpenCV Zoo) and
cached. `.gitignore` excludes media, transcripts, and `.env` so private material
is not committed by accident.

## Licences

This project is **Apache-2.0**. It incorporates MIT-licensed work from
browser-use/video-use, whose notice is retained.

Two things worth knowing before you rely on them:

- **Speaker diarization** (`[diarize]` extra) uses pyannote, whose *code* is MIT
  but whose *weights are gated*: you must accept the model's terms on Hugging
  Face with your own account and supply your own token. We cannot ship one.
- **Remotion** (`[remotion]` extra, optional motion graphics) is **not open
  source**. It is free for individuals, non-profits, and for-profit
  organisations with up to three employees; larger companies need a paid
  licence. Nothing in the core pipeline requires it.

Full detail, including model licences separated from code licences, in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Limitations

Honest list of what this does not do yet:

- **Active-speaker detection.** Face-aware framing picks the most prominent
  face, not the one currently talking. Two-person `speaker` mode is therefore
  weaker than `face` mode on a single subject.
- **The shorts workflow is agent-driven**, not a single command. Candidate
  discovery and scoring exist as schemas and skill guidance; there is no
  `social-video shorts` command yet.
- **No B-roll, no music, no transitions.** Every cut is a butt-splice. This is
  deliberate for now — editing correctness first.
- **WhisperX alignment and diarization are declared extras but not wired up.**
- **Windows and macOS are covered by CI but have not been hand-tested** on real
  footage.
- **Remotion motion graphics are not implemented**, only licensed for and
  planned.
- Punch-ins are supported in the EDL but not yet chosen automatically.

## Roadmap

1. Active-speaker detection (LR-ASD) for genuine speaker-aware framing.
2. A first-class `shorts` command with candidate discovery and scoring.
3. WhisperX alignment behind `[align]`; diarization behind `[diarize]`.
4. auto-editor `v3` export, for round-tripping to Premiere, Resolve and Final Cut.
5. Caption correction workflow.
6. Optional Remotion layer for motion graphics.

## Contributing

`uv run pytest` and `uv run ruff check .` before opening anything. Media fixtures
are generated by tests, never committed. If a change is a generic fix rather than
social-video behaviour, consider whether it belongs upstream first — see
[UPSTREAM.md](UPSTREAM.md).
