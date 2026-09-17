# social-video-agent

An agent-native, local-first editor for turning existing recordings into Reels and Shorts. Codex makes editorial decisions from an inspectable transcript; FFmpeg performs frame-accurate cuts and audio, and Remotion adds a planned motion-design layer. Sources are never modified, and no paid AI API key is required.

```text
source → local transcription → edit plan → EDL + motion plan → FFmpeg base → Remotion → QA
```

The project is an alpha. The FFmpeg pipeline, default Remotion compositor,
captions, local faster-whisper backend, profiles, and QA are implemented.
WhisperX alignment and diarization remain optional future integrations.

## Windows 11 + Codex + WSL2

This is the Tier 1 setup. ChatGPT Desktop runs on Windows, while Codex and every media tool run inside WSL2. Do not install a second copy of Python, FFmpeg, or Node natively on Windows for this workflow.

1. Install WSL2 from an Administrator PowerShell terminal, then restart if Windows requests it:

   ```powershell
   wsl --install
   ```

2. In the ChatGPT desktop app open **Settings → Agent environment**, choose **Windows Subsystem for Linux**, select the desired distribution if offered, and restart the app.

3. Open WSL and clone the repository into the Linux filesystem:

   ```bash
   mkdir -p ~/projects
   cd ~/projects
   git clone https://github.com/bartlomiejborzucki/social-video-agent.git
   cd social-video-agent
   ./scripts/wsl/bootstrap.sh
   social-video-agent doctor
   ```

4. Add or open `~/projects/social-video-agent` in Codex and ask:

   > Edit this video into a vertical Reel.

Microsoft recommends keeping Linux-tool projects in the WSL filesystem. Do not use `/mnt/c/Users/.../social-video-agent` as the normal repository location: Git, Python environments, `node_modules`, frame extraction, and render caches are substantially slower across the mounted Windows filesystem boundary.

### Windows media paths

Source and final media may still live on Windows drives:

```text
C:\Users\User\Videos\Mój film.mp4
↕
/mnt/c/Users/User/Videos/Mój film.mp4
```

Both forms are accepted inside WSL. Pasted drive-letter paths are converted with `wslpath`; spaces and Polish characters are passed as ordinary subprocess arguments, never through a shell.

```bash
social-video-agent inspect 'C:\Users\User\Videos\Mój film.mp4'
social-video-agent edit '/mnt/c/Users/User/Videos/Mój film.mp4' \
  --output '/mnt/c/Users/User/Videos/output/'
```

For a source under `/mnt/c` or `/mnt/d`, high-I/O intermediate data is stored under `~/.cache/social-video-agent/workspaces/` in Linux. Only the requested final file is copied to the Windows destination. Override the cache root with `SOCIAL_VIDEO_HOME`.

Native Windows is not the primary supported runtime. There is no PowerShell launcher, `wsl.exe` bridge, native Windows execution engine, Docker service, MCP server, or cloud backend.

### Remotion is enabled by default

Bootstrap installs the exact Node packages from `package-lock.json`, downloads
Chrome Headless Shell through Remotion's official command, type-checks the
composition, and runs a real offline MP4 smoke render. `doctor` treats Node,
Remotion, and its browser as required. Keep both the repository and
`node_modules` in the WSL filesystem.

Remotion uses a source-available license rather than Apache-2.0. Stage 0 stops
before project discovery or media processing until the user records one of:

- `free_license_eligible` — after confirming the current free-license terms;
- `company_license_confirmed` — after obtaining the applicable Company License.

See the [current Remotion license](https://www.remotion.dev/license). The CLI
does not decide legal eligibility. Users who explicitly do not want Remotion
may select `--renderer ffmpeg`, but that is an opt-out from the default visual
pipeline.

## Project-aware editing

`social-video-agent` starts from the project, not generic editing defaults. When
invoked from a repository it performs a bounded local discovery pass before
editorial planning. It looks for explicit `social-video.yaml` configuration,
applicable `AGENTS.md`, brandbooks, video and tone-of-voice guidelines, fonts,
logos, templates, and relevant design assets. It skips `.git`, dependencies,
virtual environments, builds, caches, models, renders, and temporary frames; it
does not recursively ingest the whole repository.

The target project root is distinct from the installed plugin/skill root. All
findings are saved per edit under:

```text
edit/context/project-context.json
edit/context/project-context.md
edit/context/context-sources.json
```

Explicit user instructions have highest priority, followed by project-specific
social-video config, project instructions, video guidance, brand guidance,
templates, the general design system, previous outputs, and finally skill
defaults. Claims carry a source and confidence; heuristic colors or web fonts
are not silently promoted to video rules.

Inspect or refresh discovery deterministically:

```bash
social-video-agent context inspect . --workspace edit
social-video-agent context refresh . --workspace edit
```

An optional `.social-video/config.yaml` (or `social-video.yaml`) may specify
only the fields the project needs, for example:

```yaml
brand_name: Example
content_language: pl
editing_profile: calm-educational
model_budget: balanced
caption_style:
  position: lower_safe_zone
font: assets/fonts/Inter-Regular.ttf
brand_colors: ["#F4C542"]
logo: assets/logo.svg
editing_guide: docs/video-guidelines.md
```

Private local brand assets may remain gitignored. Discovery reads them locally
but never copies them into this plugin or uploads them.

The root, cache, and state decisions are recorded in
[ADR-003](docs/architecture/ADR-003-project-context-and-staged-workflow.md).

## Guided multi-model workflow

The default interactive workflow persists state in `edit/workflow-state.json`,
so changing model or starting a new Codex conversation does not lose progress:

| Stage | OpenAI recommendation | Claude alternative | Work |
|---|---|---|---|
| 0/1 | Sol (high) | Claude Opus 5 | discovery + editorial plan |
| 2 | Terra (medium) | Claude Sonnet 5 | EDL + captions + preview + QA |
| 3 | Sol (high) | Claude Opus 5 | supervising-editor review |
| 4 | Terra (medium) | Claude Sonnet 5 | approved fixes + final render |
| 5 | Luna (low) | Claude Haiku 4.5 | optional mechanical variants |

Astra and Claude Fable 5.1 are not normal steps. They are suggested only for a
genuinely difficult narrative reconstruction or deep technical impasse. Claude
recommendations apply only when that provider is available in the user's host;
the skill never claims to switch provider or model automatically. Model names
are mapped from stable conceptual tiers in one configuration file, so future
model-name changes do not alter workflow schemas.

Initialize and inspect a workflow:

```bash
social-video-agent workflow init interview.mp4 --project-root . \
  --remotion-license free_license_eligible --language pl
social-video-agent workflow status edit --language pl
social-video-agent workflow complete 1 --workspace edit --language pl
```

At each boundary, including entry to Stages 4 and 5, the agent validates
artifacts, saves state, stops, shows the OpenAI recommendation and Claude
alternative, explains why, and gives a short continuation prompt. It does
not claim to switch the user's model automatically. Ask “Where are we?” or
“Continue social-video-agent with Stage 2” in a new conversation to resume.

Use `--workflow-mode continuous` or say “Do everything with the current model”
to run all stages without handoff stops. “Just make it quickly” does the same,
but context discovery, artifacts, source safety, and QA remain mandatory.
Budgets are `economical`, `balanced`, and `quality`; Astra is never selected
automatically.

Example:

> User: Use social-video-agent to turn interview.mp4 into a Reel.
>
> Agent: I found `docs/brandbook.pdf`, `docs/video-guidelines.md`, and
> `assets/logo.svg`. I will use the calm educational profile and project
> typography. Stage 1 will create the editorial plan without rendering.
>
> Agent after Stage 1: Stage 1 complete. Switch to Terra and send:
> “Continue social-video-agent with Stage 2.”

Before that first discovery, the agent explains the Remotion license gate and
records the user's declaration. Stage 2 writes both `edl.json` and
`motion-plan.json`. The motion plan is project-aware and reviewable: it may use
restrained hook typography, lower thirds, callouts, and a designed end card,
but every element needs a timeline interval and reason. It does not add random
zooms, transitions, or motion merely to appear busy. A clean edit with no extra
graphic is valid when that serves the material better.

## What works

- Local transcription with faster-whisper, downloaded on first transcription and cached under `~/.cache/social-video-agent/models/`.
- Horizontal and vertical sources, compatible CFR 30/29.97/60/59.94 exports,
  multiple audio tracks, sample-derived AAC timestamps, and deterministic EDL rendering.
- Face-aware 9:16 framing with restrained movement.
- ASS captions with preflight glyph checks, including `Zażółć gęślą jaźń`.
- Project-aware Remotion motion design with exact pinned dependencies, a
  durable `motion-plan.json`, H.264/AAC social export, and real render smoke QA.
- Profiles for talking heads, education, podcasts, stories, landscape, square, and faster social editing.
- Mechanical QA for duration, audio, clipping, silence at cuts, black frames, and caption bounds.
- Content-addressed transcription caching and immutable source files.

## CLI

The canonical command is `social-video-agent`; `social-video` remains as a compatibility alias.

```bash
social-video-agent doctor
social-video-agent context inspect . --workspace edit
social-video-agent workflow init INPUT --project-root . \
  --remotion-license free_license_eligible --language en
social-video-agent workflow status edit
social-video-agent inspect INPUT
social-video-agent transcribe INPUT
social-video-agent pack WORKSPACE
social-video-agent plan INPUT --profile talking-head --goal '45 second Reel'
social-video-agent edit INPUT --profile talking-head
social-video-agent render WORKSPACE --quality preview --output /path/to/preview.mp4
social-video-agent qa WORKSPACE
social-video-agent apply-editorial-qa WORKSPACE
```

`social-video-agent doctor` checks this project's WSL/Linux environment,
FFmpeg, Python dependencies, ASR, fonts, Node, locked Remotion packages,
Chrome Headless Shell, plugin files, and workspace. OpenAI's separate
`codex doctor` checks Codex itself; the commands are complementary.

GPU/CUDA is optional. CPU mode is supported and setup never installs NVIDIA drivers, CUDA, Docker, or Whisper models. Models download only when transcription first needs one.

## Linux and macOS

The pipeline remains cross-platform. Install Python 3.10–3.13, `uv`, FFmpeg
with libass, fontconfig, a font with the required glyphs, Node.js 20+, and npm,
then run:

```bash
uv sync --extra dev
npm ci
npx remotion browser ensure
uv run social-video-agent doctor
```

The WSL bootstrap is intentionally Linux-only and its automatic package installation targets Ubuntu/Debian. Unsupported distributions receive the exact prerequisite list instead of an attempted `apt` command. macOS users should verify that their FFmpeg build contains the `subtitles` filter.

## Codex plugin and canonical skill

The one canonical skill is `skills/social-video-agent/SKILL.md`. Plugin metadata follows the current Codex layout:

```text
.codex-plugin/plugin.json
.agents/plugins/marketplace.json
plugins/social-video-agent/
skills/social-video-agent/
```

Install from GitHub:

```bash
codex plugin marketplace add bartlomiejborzucki/social-video-agent
codex plugin add social-video-agent@social-video-agent
```

For local development and update instructions, see [docs/plugin-installation.md](docs/plugin-installation.md). The plugin/skill provides workflow knowledge; it does not contain FFmpeg, a virtual environment, `node_modules`, or model weights. ChatGPT Work does not execute this local media runtime; use Codex with its agent environment set to WSL2.

Build a lightweight skill upload artifact with:

```bash
./scripts/build-skill.sh
```

This creates `dist/social-video-agent-skill.zip` without runtime dependencies or private media.

## Development and release checks

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy
uv run python scripts/validate_distribution.py
social-video-agent doctor
./scripts/release-check.sh
```

Tiny media fixtures are generated deterministically with FFmpeg. Automated Linux CI covers unit tests, plugin/skill/package validation, 30/60 fps rendering, paths with spaces and Polish Unicode, caption burn-in, and source immutability. GitHub-hosted Linux is not WSL: actual `/mnt/c` behavior and WSL detection remain a manual release gate in [docs/testing/windows-wsl2-acceptance.md](docs/testing/windows-wsl2-acceptance.md).

A dedicated CI job installs Node 24, the locked Remotion graph and Chrome
Headless Shell, type-checks the React composition, renders a synthetic Polish
fixture, verifies CFR/AAC timing, runs technical QA, and fully decodes both
streams. It still does not pretend that generic Linux is a real `/mnt/c` test.

The social delivery contract is MP4 with H.264/`avc1`, `yuv420p`, BT.709,
compatible constant frame rate, AAC-LC stereo at 48 kHz with continuous sample
timestamps, `faststart`, 720×1280 preview, and 1080×1920 final. Rendering first
finishes and fully decodes a private file in Linux cache, then atomically
publishes `preview.mp4` or `final.mp4`; a partial MP4 never appears under the
destination name. Technical QA always writes `qa-report.json`.

If a privacy-safe picture ends before its audio, validation requires an
explicit EDL ending strategy. It will not silently create a multi-second still.
See [the artifact contract](skills/social-video-agent/references/artifacts.md).

## Privacy and licenses

Media processing is local by default. Models are downloaded once on first use and are not committed. Cloud transcription, if added explicitly, must disclose that media leaves the machine.

The project is Apache-2.0 and incorporates attributed MIT-licensed work from [browser-use/video-use](https://github.com/browser-use/video-use). See [UPSTREAM.md](UPSTREAM.md), [NOTICE](NOTICE), and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Known limitations

- The legacy `edit` command remains a continuous mechanical path; normal skill use now creates a project-aware staged plan and stops at guided handoffs.
- The multi-short workflow is agent-driven; there is no single `shorts` command yet.
- WhisperX alignment and speaker diarization are declared optional dependencies but are not connected to the pipeline.
- Remotion currently composites a deliberately small vocabulary of project-aware
  hook, lower-third, callout, and end-card graphics. It does not automatically
  invent bespoke illustration, 3D work, or brand animation. Professional quality
  still depends on the source, project guidance, Stage 1 decisions, and Stage 3
  supervising-editor review.
- Legacy workspaces resume with the FFmpeg renderer for compatibility. New
  workflows default to Remotion and require the Stage 0 declaration.
- Face-aware framing follows the most prominent face, not the active speaker.
- Actual Windows 11 `/mnt/c` acceptance must be recorded for each release; generic Linux CI is not equivalent.

See [CHANGELOG.md](CHANGELOG.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md) for public project policies.
