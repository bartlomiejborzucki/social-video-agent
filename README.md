# social-video-agent

**An agent-native, local-first editor that turns existing recordings into Reels,
Shorts and TikToks.**

A coding agent (Codex or Claude) makes the editorial decisions from an
inspectable transcript. FFmpeg cuts frame-accurately, Remotion adds a designed
motion layer, and every step leaves an artifact you can read, change and resume
from. Sources are never modified, media stays on your machine, and no paid AI
API key is required.

```text
recording → local transcript → edit plan → EDL + motion plan → FFmpeg base → Remotion → QA → delivery
```

**Contents:** [What it can do](#what-it-can-do) ·
[Quick start](#quick-start) · [Installation](#installation) ·
[How it works](#how-it-works) · [Motion design](#motion-design) ·
[CLI](#cli) · [Development](#development-and-releases) ·
[Privacy and licences](#privacy-and-licences) ·
[Known limitations](#known-limitations)

## What it can do

**Edit from the transcript**
- Local transcription with faster-whisper (Polish, English and every other
  Whisper language) with word timings and content-addressed caching; optional
  WhisperX word alignment and pyannote speaker diarization.
- An editorial plan the agent writes and you review, compiled into a
  word-aligned EDL. Nothing is cut that the plan does not say.
- Cut candidates found from timing — hesitations (`yyy`, `eee`, `um`), doubled
  words, restarted phrases, long pauses — applied only when the agent accepts
  them.
- One long recording into several standalone shorts.

**Motion that holds a viewer**
- One `motion_energy` setting — `calm`, `lively`, `bold` — sets punch-ins,
  transitions, accent density and caption animation together.
- Accent candidates found in what is said: a hook card from the first line,
  counting figures, numbered steps, callouts for questions, push-ins on
  punchlines and turns, transitions on jumping cuts — snapped to the beat of a
  licensed music bed.
- Fifteen brand-driven graphics in three style packs, from hook cards and lower
  thirds to charts, before/after comparisons and logo reveals.
- Sound under the motion from your own library, b-roll from your own clips,
  hook A/B variants and a review sheet of every animated moment.

**Captions that match the brand**
- Laid out against the real font's metrics and never truncated.
- Active-word highlight with `pop` or `box` animation, brand-keyword emphasis,
  per-speaker colours and rounded boxes — drawn by both renderers.
- Glyph preflight, so `Zażółć gęślą jaźń` renders instead of empty boxes.

**Framing for 9:16**
- Face-aware reframing with smoothing and scene-cut snapping; speaker framing
  that follows diarized turns and cuts between faces.
- Split layouts: two speakers stacked, or a screen share above the presenter.

**Audio**
- Measured voice cleanup: only the repairs a recording needs, each with a
  ceiling, every change reported.
- Loudness normalisation, licence-gated music beds with ducking, and sound
  effects.

**Checks before anything ships**
- Technical QA of every render against its EDL, brand QA against an executable
  brand contract, and per-platform safe zones for Reels, Shorts and TikTok.

**Delivery and handoff**
- Immutable delivery variants with a verified manifest, SRT/VTT or burned-in
  captions, covers and validated publishing metadata.
- The cut exported to Premiere, Final Cut, DaVinci Resolve (FCPXML),
  OpenTimelineIO and CMX 3600, frame for frame with the render.

**A workflow an agent can resume**
- Six persistent stages, each gated on the artifacts the next one needs, with a
  recommended model per stage and a ready-to-send continuation prompt.
- Linux, macOS and Windows 11 through WSL2, including a native Windows agent
  driving the engine in WSL2.

## Quick start

A complete pass by hand, on the FFmpeg route so it needs neither a licence
declaration nor a motion plan:

```bash
social-video-agent doctor
social-video-agent workflow init interview.mp4 --project-root . --renderer ffmpeg
social-video-agent plan interview.mp4 -w edit --goal '45 second Reel'
social-video-agent cuts find interview.mp4 -w edit        # review the candidates
social-video-agent cuts accept -w edit --kind pause --confidence high
social-video-agent compile interview.mp4 -w edit --force
social-video-agent render edit --quality preview
social-video-agent qa edit --platform reels
social-video-agent export edit                            # hand the cut to an NLE
```

In normal use you simply ask the agent — *“Edit this video into a vertical
Reel”* — and the skill runs these steps, adds the Remotion motion layer after
the Stage 0 licence declaration, and stops at each stage boundary.

## Installation

### Windows 11 with Codex in WSL2 (recommended)

ChatGPT Desktop runs on Windows while Codex and every media tool run inside
WSL2. Do not install a second copy of Python, FFmpeg or Node on Windows.

1. Install WSL2 from an Administrator PowerShell, then restart if asked:

   ```powershell
   wsl --install
   ```

2. In ChatGPT Desktop open **Settings → Agent environment**, choose **Windows
   Subsystem for Linux**, pick the distribution and restart the app.

3. In WSL, clone into the Linux filesystem and bootstrap:

   ```bash
   mkdir -p ~/projects && cd ~/projects
   git clone https://github.com/bartlomiejborzucki/social-video-agent.git
   cd social-video-agent
   ./scripts/wsl/bootstrap.sh
   social-video-agent doctor
   ```

4. Open `~/projects/social-video-agent` in Codex and ask for an edit.

Keep the repository in the WSL filesystem, not under `/mnt/c`: Git, Python
environments, `node_modules`, frame extraction and render caches are much slower
across the mounted Windows drive. Your media may stay on Windows — see
[Windows media paths](#windows-media-paths).

### Native Windows agent, engine in WSL2 (hybrid)

When the agent itself runs natively on Windows, it keeps its own tools —
ImageGen, Canva MCP, Windows Chrome — and delegates every media operation to the
engine in WSL2 through one bridge,
[`scripts/windows/social-video-agent.ps1`](scripts/windows/social-video-agent.ps1).

Install from inside WSL:

```bash
./scripts/wsl/bootstrap.sh              # the engine, in WSL only
python3 scripts/install_skills.py       # copies the skill to Windows .agents\skills
```

Then, from PowerShell:

```powershell
.\scripts\windows\social-video-agent.ps1 doctor
.\scripts\windows\social-video-agent.ps1 -Distribution Ubuntu-24.04 doctor
```

The adapter passes arguments as an array, starts the engine with
`wsl.exe --exec` by its absolute path, never uses `Invoke-Expression` or
`sh -lc`, tells the engine the agent is on Windows (so `runtime.json` records
`windows-agent-wsl-runtime`), passes stdout, stderr and the exit code through,
and refuses to fall back to `ffmpeg.exe`, Windows Python or Windows Node. With
several WSL 2 distributions and no default it stops rather than choosing one.

`runtime_mode: auto` detects the mode from the real platform of the agent
process — never from a terminal preference. Pin it with `runtime_mode:` or
`SOCIAL_VIDEO_RUNTIME_MODE`, and name a distribution with `wsl_distribution:` or
`SOCIAL_VIDEO_WSL_DISTRIBUTION`.

**Updating a 1.0.0 hybrid installation:** pull inside WSL, rerun
`./scripts/wsl/bootstrap.sh` and `python3 scripts/install_skills.py` (it
replaces the old Linux symlink on the Windows side with a real copy), and start
a new Codex session. A manual `/usr/local/bin/social-video-agent` link is no
longer needed.

### Linux and macOS

Install Python 3.10–3.13, `uv`, FFmpeg with libass, fontconfig, a font with the
glyphs you need, Node.js 20+ and npm, then:

```bash
uv sync --extra dev
npm ci
npx remotion browser ensure
uv run social-video-agent doctor
```

The WSL bootstrap targets Ubuntu/Debian; other distributions get the exact
prerequisite list instead. On macOS check that your FFmpeg has the `subtitles`
filter.

### From a release wheel

A wheel from a GitHub release carries the compositor sources but not Remotion
itself. Install Remotion's locked packages and headless browser once:

```bash
social-video-agent doctor --install-remotion
```

### Codex and Claude plugin

The one canonical skill is
[`skills/social-video-agent/SKILL.md`](skills/social-video-agent/SKILL.md).

```bash
codex plugin marketplace add bartlomiejborzucki/social-video-agent
codex plugin add social-video-agent@social-video-agent
```

See [plugin installation](docs/plugin-installation.md). The plugin carries
workflow knowledge only — no FFmpeg, virtual environment, `node_modules` or
model weights. `./scripts/build-skill.sh` builds a lightweight
`dist/social-video-agent-skill.zip`.

### Checking the setup

`social-video-agent doctor` checks the runtime mode, FFmpeg and libass, Python
dependencies, local transcription, fonts, Node, the locked Remotion packages,
Chrome Headless Shell, plugin files and the workspace, and says what to do about
every failure. GPU/CUDA is optional; models download only when transcription
first needs one.

## How it works

### Staged workflow

State lives in `edit/workflow-state.json`, so changing model or starting a new
conversation loses nothing. Each stage is gated on the artifacts the next one
needs:

| Stage | Work | OpenAI | Claude |
|---|---|---|---|
| 0/1 | discovery, licence declaration, editorial plan | Astra (high) | Claude Opus 5 |
| 2 | EDL, captions, motion plan, preview, technical QA | Sol (medium) | Claude Sonnet 5 |
| 3 | supervising-editor review | Astra (high) | Claude Opus 5 |
| 4 | approved fixes, final render, brand QA | Sol (medium) | Claude Sonnet 5 |
| 5 | delivery variants | Luna (low) | Claude Haiku 4.5 |

At each boundary the agent saves state, stops, names the recommended model and
gives a short continuation prompt; it never claims to switch models itself. Ask
*“Where are we?”* to resume. `--workflow-mode continuous` runs every stage
without stops, with every artifact and check still in place. Budgets are
`economical`, `balanced` and `quality`; the escalation tier (Claude Fable 5.1)
is never chosen automatically.

```bash
social-video-agent workflow init interview.mp4 --project-root . --language pl
social-video-agent workflow status edit --language pl
social-video-agent workflow complete 1 --workspace edit --language pl
```

### Project context and the brand contract

The agent starts from the project, not from generic defaults. A bounded
discovery pass reads `social-video.yaml`, `AGENTS.md`, brandbooks, video and
tone-of-voice guides, fonts, logos and templates — skipping `.git`,
dependencies, builds, caches and renders — and records every claim with its
source in `edit/context/`. Explicit user instructions always win.

`social-video-agent config init .` writes `.social-video/config.yaml`;
`config validate` compiles it into an executable `brand-contract.json` that
every render and brand QA are held to. Specify only what the project needs:

```yaml
schema_version: 1
brand_name: Example
font: Lato
font_file: assets/fonts/Lato-Bold.ttf
brand_colors: ["#28BCA5"]
caption_style:
  background_color: "#28BCA5"
  background_style: rounded_box
  active_word_highlight: true
  animation: pop
  emphasis_words: [Studio, 5G]
motion_energy: lively
style_pack: editorial
music_policy: none
sfx_policy: optional
audio_cleanup_policy: measured
default_resolution: "1080x1920"
delivery_output: exports/social
```

A config from before 0.4 stays valid discovery context; `config migrate` lists
each value that needs a human decision and never guesses an editorial one.

### Captions

Captions are laid out in Python against the project font's own metrics and
handed to the renderer as explicit lines, so nothing is wrapped, clamped or
ellipsised later. A cue that does not fit is wrapped, then shrunk (to at most
72% of its size), then refused with its text named — never truncated.

| Key | Reference | Why |
|---|---|---|
| `font_size_pct` | `3.6` | ~69 px at 1080×1920; an ordinary Polish phrase fits two lines |
| `max_words_per_cue` / `max_chars_per_cue` | `4` / `24` | the sentence breaks on words before the frame edge |
| `bottom_margin_pct` | `22` | clears the platform UI |
| `outline_or_shadow` | `none` | an outline on a box costs line width |

Brand QA checks what was drawn: lost text, an added ellipsis, a line wider than
the box, a missing highlight, emphasis or animation.

### Voice cleanup

`audio_cleanup_policy: measured` measures the recording first — noise floor,
rumble, mains hum, sibilance, loudness range, clipping — and applies only what
crosses its threshold, each repair capped:

| Measured | Applied | Ceiling |
|---|---|---|
| energy below 60 Hz within 15 dB of the voice | high-pass at 80 Hz | two poles |
| a narrow mains tone within 18 dB of the voice | notch at the fundamental | −15 dB |
| SNR under 20 dB over an audible floor | `afftdn` | 10 dB |
| 5–9 kHz within 8 dB of the voice | de-esser | 0.15 |
| loudness range over 12 LU | compressor | 2:1 |
| peaks at or above −0.1 dBFS | nothing | reported, never repaired |

A clean recording comes out untouched. Every render lists what it changed and
how to undo it (`--no-audio-cleanup` or `audio_cleanup_policy: none`).

### Remotion and its licence

Remotion is the default compositor. It uses a source-available licence, so
Stage 0 stops until the user records `free_license_eligible` or
`company_license_confirmed` after reading the
[current terms](https://www.remotion.dev/license). Declare once per project:

```bash
social-video-agent remotion-license attest free_license_eligible --project-root . --accept-terms
social-video-agent remotion-license status --project-root .
```

The declaration is stored beside the config, asked again after a revocation, a
new release line or a year, and never derived from company data. Projects that
cannot use Remotion render with `--renderer ffmpeg`, which still draws rounded
caption boxes, highlights and emphasis; `workflow renderer remotion` switches an
existing workspace later.

### Windows media paths

Media may live on Windows drives. Inside WSL both forms are accepted, and a
pasted drive-letter path is converted once with `wslpath`:

```text
C:\Users\User\Videos\Mój film.mp4   ↔   /mnt/c/Users/User/Videos/Mój film.mp4
```

For a source under `/mnt/<drive>`, heavy intermediates stay in
`~/.cache/social-video-agent` and only the final file is copied back. Override
the cache root with `SOCIAL_VIDEO_HOME`.

### Images and plates

Cover and end-card backgrounds may come from the user's own material, a real
frame, Canva, the agent's own image tool, or the OpenAI/Gemini APIs with the
user's key — in that order of preference, with consent, and blocked entirely by
`image_generation_policy: none`. Every word on screen is drawn locally; image
tools only draw backgrounds. See
[generated visuals](skills/social-video-agent/references/generated-visuals.md).

### Delivery and handoff

Rendering finishes and fully decodes a private file first, then publishes it
atomically — a partial MP4 never appears under its final name. The delivery
contract is H.264 `yuv420p` BT.709, constant frame rate, AAC-LC stereo 48 kHz,
`faststart`, 720×1280 preview and 1080×1920 final.

```bash
social-video-agent deliver edit --output ./delivery --with-captions --srt --vtt --poster --publish
social-video-agent export edit --format fcpxml
```

`delivery-manifest.json` records every file with its hash and the identical EDL
hash from before and after delivery. `export` writes FCPXML, Premiere/FCP7 XML,
OpenTimelineIO and CMX 3600, and lists what a timeline cannot carry.

## Motion design

A well-cut short that never moves reads as a recording. The skill gives every
cut a rhythm — something changes every 3–5 seconds — sized to the project's
energy level:

| `motion_energy` | Punch-in up to | Transitions | Accents | Spoken word |
|---|---|---|---|---|
| `calm` | 1.12 | none | ~4/min | highlight |
| `lively` | 1.18 | ~4/min | ~10/min | `pop` |
| `bold` | 1.25 | ~8/min | ~16/min | `box` |

**Accents from what is said.** `motion suggest` finds the hook (the first line,
as a full-frame hook card), figures (a counting stat), enumerations (numbered
steps), questions (a callout), punchlines and turns (“ale”, “instead”: a
push-in) and jumping cuts (a transition). Each has an id and a confidence,
spaced to the energy level and snapped to the beats of a licensed music bed.
Nothing changes until the agent accepts it:

```bash
social-video-agent motion suggest interview.mp4 -w edit
social-video-agent motion accept -w edit acc-001 acc-003 --kind transition
```

**Graphics.** Fifteen types, each with a timeline interval and a reason:
`hook_card`, `hook`, `lower_third`, `callout`, `quote`, `stat`, `chart`,
`compare`, `list`, `steps`, `chapter`, `cta`, `progress`, `logo_reveal` and
`end_card`. `style_pack` — `editorial`, `bold-social` or `tech-minimal` — sets
their look in the brand's colours and font. Transitions (`zoom`, `slide`,
`flash`) sit on cuts; punch-ins move the picture while captions and graphics
stay put.

**Sound, b-roll and review.**

```bash
social-video-agent motion sfx ./sfx -w edit --licensed      # whoosh, pop, hit from your library
social-video-agent broll suggest interview.mp4 --library ./b-roll -w edit
social-video-agent broll accept -w edit br-001
social-video-agent motion variants -w edit --text "Hook A" --text "Hook B"
social-video-agent motion sheet -w edit                     # qa/motion-sheet.png
```

B-roll is matched by file name and tags, tolerant of Polish inflection
(“samochodu” finds `samochod.mp4`). Sound and music are always the user's own
licensed files; the tool never sources or clears audio. The render refuses any
movement above the energy level's limits.

## CLI

The command is `social-video-agent` (`social-video` is an alias). Every command
that reports information supports `--json`.

| Area | Commands |
|---|---|
| Setup | `doctor`, `version`, `profiles`, `config init/validate/migrate`, `remotion-license`, `context inspect/refresh` |
| Workflow | `workflow init/status/resume/complete/renderer` |
| Source | `inspect`, `fetch URL --rights "..."`, `transcribe [--diarize]`, `pack` |
| Editing | `plan`, `cuts find/accept`, `compile`, `shorts list/create`, `apply-editorial-qa` |
| Motion | `motion suggest/accept/sfx/variants/sheet`, `broll suggest/accept` |
| Render and check | `render`, `edit`, `qa`, `platforms` |
| Images | `image status/prompt/register/capabilities/plate`, `cover` |
| Output | `deliver`, `export` |

Run `social-video-agent COMMAND --help` for options.

## Development and releases

```bash
uv sync --extra dev
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run python scripts/validate_distribution.py
./scripts/release-check.sh
```

Media fixtures are generated deterministically with FFmpeg. CI runs Python
3.10–3.13, FFmpeg 6 and 7, unit tests on Windows and macOS, PowerShell
adapter tests against a stand-in `wsl.exe`, real Remotion renders, wheel
installation and NLE exports read back by OpenTimelineIO. Generic Linux CI is
not a real Windows machine: the [Windows 11 acceptance
checklist](docs/testing/windows-wsl2-acceptance.md) is a manual release gate.
Releasing and PyPI trusted publishing are described in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Privacy and licences

Media processing is local. Models are downloaded once on first use and never
committed. Nothing leaves the machine unless the user asks for it — an image
prompt to a cloud tool, a URL download — and says so.

The project is Apache-2.0 and includes attributed MIT-licensed work from
[browser-use/video-use](https://github.com/browser-use/video-use). See
[UPSTREAM.md](UPSTREAM.md), [NOTICE](NOTICE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Known limitations

- Clip selection for multi-short workflows and every accepted cut, accent and
  b-roll clip stay editorial decisions: the code proposes, the agent decides.
- Platform safe zones are conservative estimates of the feed UI, not published
  specifications; check on a real device before a campaign.
- Music and effects are never sourced or licence-cleared by this tool.
- Speaker framing uses audio-correlated mouth motion and diarized turns, not
  neural active-speaker detection (`LR-ASD` is the recorded next step).
- WhisperX and pyannote are opt-in and not exercised in CI, which never
  installs PyTorch; diarization needs your own Hugging Face token.
- The graphics vocabulary is fixed; the tool does not invent bespoke
  illustration or 3D work.
- Word animation (`pop`, `box`) is drawn by Remotion; the FFmpeg route draws a
  colour highlight instead and brand QA says so.
- Windows 11 `/mnt/c` acceptance is recorded by hand for each release.

**Project documents:** [roadmap](docs/ROADMAP.md) ·
[changelog](CHANGELOG.md) · [contributing](CONTRIBUTING.md) ·
[security](SECURITY.md) · [architecture decisions](docs/architecture/) ·
[artifact contract](skills/social-video-agent/references/artifacts.md)
