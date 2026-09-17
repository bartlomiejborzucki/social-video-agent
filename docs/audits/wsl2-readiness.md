# WSL2 readiness audit

Audit date: 2026-09-16. Target: Windows 11 → ChatGPT Desktop → Codex agent in WSL2 → one Linux media runtime.

Status meanings: **READY** is implemented and covered by an automated or recorded manual check; **PARTIAL** works with a stated limit or still needs a real Windows acceptance run; **MISSING** is not implemented.

| Area | Before | After | Evidence / limitation |
|---|---|---|---|
| Python package and CLI | PARTIAL | READY | Modern `pyproject.toml`, uv lock, and both `social-video-agent` plus legacy `social-video` entry points. |
| Local faster-whisper transcription | READY | PARTIAL | Required dependency, content/options cache, and CPU fallback are present. A real model transcription was not run because bootstrap and CI intentionally avoid model downloads. |
| Linux FFmpeg/ffprobe execution | READY | READY | PATH discovery and subprocess argument arrays; end-to-end generated-media tests. |
| Source immutability | READY | READY | Render test hashes/compares the source before and after. |
| Polish captions and fonts | READY | READY | FontTools coverage check plus burned `Zażółć gęślą jaźń` smoke render. |
| 30/60 fps and horizontal/vertical media | READY | READY | Deterministic generated fixtures and ffprobe assertions. |
| Pasted Windows path normalization | MISSING | READY | Central `wslpath` helper with unit tests for spaces and Polish characters. |
| `/mnt/c` source/output support | PARTIAL | READY | A real WSL mount test rendered a Polish-named source from `C:\Temp\...`, wrote a Polish-named output to `/mnt/c`, used Linux intermediates, and verified the source hash. |
| Fast WSL workspace/cache | PARTIAL | READY | Mounted Windows sources use `~/.cache/social-video-agent/workspaces`; explicit output may return to Windows. |
| WSL bootstrap | MISSING | READY | Idempotent Ubuntu/Debian bootstrap checks packages, uv, FFmpeg, fonts, environment, smoke test, and doctor. |
| Project doctor | PARTIAL | READY | Reports platform/WSL/distro, Python env, uv, FFmpeg, ASR, required Node/Remotion/browser, optional GPU, fonts, workspace, plugin, skill, and marketplace. |
| Codex plugin manifest | PARTIAL | READY | Current `.codex-plugin/plugin.json` schema fields and offline validator; repository metadata is no longer placeholder data. |
| Repository marketplace | MISSING | READY | `.agents/plugins/marketplace.json` points to `plugins/social-video-agent` as required by current Codex discovery. |
| Canonical skill | PARTIAL | READY | One implementation at `skills/social-video-agent`; the plugin links to it and distribution validation checks it. |
| Remotion | MISSING | READY | Default for new workflows with a pre-discovery license gate, exact npm lock, Linux-side Chrome, validated motion plan, real MP4 smoke render, and blocking doctor checks. Legacy workspaces remain FFmpeg for compatibility. |
| Automated CI | PARTIAL | PARTIAL | Linux unit/integration/media/Unicode/distribution/package jobs plus macOS/Windows unit portability are defined and their local equivalents pass. No remote GitHub Actions run was observed in this audit; CI does not claim to be WSL. |
| Release packaging | MISSING | READY | Tag workflow builds wheel, sdist, skill zip, checksums, and GitHub release assets. |
| Public repository documents | PARTIAL | READY | README, Apache-2.0 license, changelog, contributing, security, AGENTS, and acceptance guide. |
| Plugin evaluation | MISSING | PARTIAL | Six meaningful prompts and rerun guidance exist. A live `plugin-eval` benchmark was not run because it is account/network-dependent. |

## Architecture found

The repository already had a well-separated Python pipeline: probe and analysis, local ASR, packed transcript, editorial plan, validated EDL, reframing, ASS captions, FFmpeg rendering, and QA. It already avoided `shell=True` and `os.system`, captured FFmpeg stderr, guarded downloaded archives against traversal, generated test media, and tested source immutability. Those algorithms were retained.

The integration gaps were around the host boundary: the installed command name, Windows-path handling in WSL, mounted-drive workspace placement, bootstrap/release automation, current Codex marketplace layout, metadata validation, and accurate WSL documentation.

## Official references checked

- [ChatGPT desktop app for Windows](https://learn.chatgpt.com/docs/windows/windows-app) confirms that Agent environment can be set to Windows Subsystem for Linux and requires an app restart.
- [OpenAI plugins repository](https://github.com/openai/plugins) uses `plugins/<name>/.codex-plugin/plugin.json` and `.agents/plugins/marketplace.json`.
- [OpenAI Codex repository plugin schema sample](https://github.com/openai/codex/blob/main/codex-rs/skills/src/assets/samples/plugin-creator/references/plugin-json-spec.md) defines current manifest and marketplace fields.
- [Microsoft WSL filesystem guidance](https://learn.microsoft.com/en-us/windows/wsl/filesystems) recommends storing Linux-tool projects in the Linux filesystem.
- [Microsoft WSL interoperability guidance](https://learn.microsoft.com/en-us/windows/dev-environment/wsl-interop) documents `/mnt/<drive>` and `wslpath` conversion.

## Security review

- No `os.system` or user-controlled `shell=True` execution was found.
- FFmpeg, ffprobe, fontconfig, Node, and `wslpath` use argument arrays.
- Sources are never output targets; `--output` rejects an exact source overwrite.
- Downloaded FFmpeg archives reject absolute and parent-traversal members. The optional downloader remains an explicit user command and is not used by bootstrap when a distro package is available.
- No credentials or private media are tracked.

## Honest release gate

Code and WSL-mounted-media tests can be ready while the Windows desktop UI path is still unverified. Do not mark a release fully Windows-ready until [the real Windows acceptance checklist](../testing/windows-wsl2-acceptance.md) passes on Windows 11 with ChatGPT Desktop. The current environment did verify real `/mnt/c` media I/O, spaces, Polish filenames/captions, Linux-cache intermediates, and source immutability.
