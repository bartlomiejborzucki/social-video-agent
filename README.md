# social-video-agent

An agent-native, local-first editor for turning existing recordings into Reels and Shorts. Codex makes editorial decisions from an inspectable transcript; Python and FFmpeg perform deterministic media work. Sources are never modified, and no paid API key is required.

```text
source → local transcription → packed transcript → edit plan → EDL → render → QA
```

The project is an alpha. The core FFmpeg pipeline, captions, local faster-whisper backend, profiles, and QA are implemented. Remotion, WhisperX alignment, and diarization are not yet wired into the runtime.

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

## What works

- Local transcription with faster-whisper, downloaded on first transcription and cached under `~/.cache/social-video-agent/models/`.
- Horizontal and vertical sources, compatible CFR 30/29.97/60/59.94 exports,
  multiple audio tracks, sample-derived AAC timestamps, and deterministic EDL rendering.
- Face-aware 9:16 framing with restrained movement.
- ASS captions with preflight glyph checks, including `Zażółć gęślą jaźń`.
- Profiles for talking heads, education, podcasts, stories, landscape, square, and faster social editing.
- Mechanical QA for duration, audio, clipping, silence at cuts, black frames, and caption bounds.
- Content-addressed transcription caching and immutable source files.

## CLI

The canonical command is `social-video-agent`; `social-video` remains as a compatibility alias.

```bash
social-video-agent doctor
social-video-agent inspect INPUT
social-video-agent transcribe INPUT
social-video-agent pack WORKSPACE
social-video-agent plan INPUT --profile talking-head --goal '45 second Reel'
social-video-agent edit INPUT --profile talking-head
social-video-agent render WORKSPACE --quality preview --output /path/to/preview.mp4
social-video-agent qa WORKSPACE
social-video-agent apply-editorial-qa WORKSPACE
```

`social-video-agent doctor` checks this project's WSL/Linux environment, FFmpeg, Python dependencies, ASR, fonts, plugin files, and workspace. OpenAI's separate `codex doctor` checks Codex itself; the commands are complementary.

GPU/CUDA is optional. CPU mode is supported and setup never installs NVIDIA drivers, CUDA, Docker, or Whisper models. Models download only when transcription first needs one.

## Linux and macOS

The Python pipeline remains cross-platform. Install Python 3.10–3.13, `uv`, FFmpeg with libass, fontconfig, and a font with the required glyphs, then run:

```bash
uv sync --extra dev
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

- The `edit` command creates a mechanical first pass; the skill expects Codex to review the packed transcript and revise editorial choices.
- The multi-short workflow is agent-driven; there is no single `shorts` command yet.
- WhisperX alignment and speaker diarization are declared optional dependencies but are not connected to the pipeline.
- Remotion is not enabled. Node is therefore optional in v0.1.0, and no `node_modules` directory should be created on `/mnt/c`.
- Face-aware framing follows the most prominent face, not the active speaker.
- Actual Windows 11 `/mnt/c` acceptance must be recorded for each release; generic Linux CI is not equivalent.

See [CHANGELOG.md](CHANGELOG.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md) for public project policies.
