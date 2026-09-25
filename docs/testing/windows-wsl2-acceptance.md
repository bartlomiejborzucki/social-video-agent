# Windows 11 + Codex + WSL2 acceptance

Run this checklist on a real Windows 11 machine. Generic Linux CI does not prove `/mnt/c` behavior.

- [ ] In ChatGPT Desktop, set **Settings → Agent environment → Windows Subsystem for Linux**, select the distribution, and restart the app.
- [ ] Clone the repository to `~/projects/social-video-agent`, not `/mnt/c`.
- [ ] Run `./scripts/wsl/bootstrap.sh`.
- [ ] Confirm the Remotion license choice, initialize a workflow with
      `--remotion-license free_license_eligible` or
      `company_license_confirmed`, and verify the declaration is persisted.
- [ ] Record it for the project with `social-video-agent remotion-license attest
      DECLARATION --project-root PROJECT --accept-terms`, verify
      `remotion-license status` reports it as usable, then initialize a second
      workspace with no `--remotion-license` flag and confirm Stage 0 continues
      and records `remotion_license_source: project_declaration`.
- [ ] Run `social-video-agent remotion-license revoke --project-root PROJECT`
      and confirm a new `workflow init` stops with the recorded reason.
- [ ] Run `social-video-agent doctor`; Node, Remotion, Chrome Headless Shell,
      and the final summary are `OK`/`READY`.
- [ ] From a separate fake target project containing `AGENTS.md`, brand/video
      docs, and a logo, run `social-video-agent workflow init ... --project-root
      ...`; verify only target-project files appear in `context-sources.json`.
- [ ] Complete Stage 1 and open a new Codex conversation. Ask “Where are we?”;
      verify state resumes at Stage 2 and recommends the configured execution
      model without repeating discovery.
- [ ] Run `./scripts/smoke-test.sh` to generate and edit deterministic media.
- [ ] Run `uv run python scripts/manual_wsl_acceptance.py --mount-root /mnt/c/Temp`.
- [ ] Inspect and edit a source under `/mnt/c/...`.
- [ ] Repeat with `/mnt/c/Users/Test User/Videos/Mój film testowy 01.mp4`.
- [ ] Verify a caption containing `Zażółć gęślą jaźń` has no missing glyphs.
- [ ] Verify both 30 fps and 60 fps fixtures.
- [ ] Play `preview.mp4` and `final.mp4` in VLC and Windows Media Player; both
      have smooth CFR video and complete audible audio.
- [ ] Inspect `qa/ending-contact-sheet.png`, the final ten seconds, final five
      seconds densely, and the last frame; confirm motion remains purposeful or
      an intentional end card/hold is documented.
- [ ] Confirm `qa-report.json` reports matching audio/video duration, normal AAC
      cadence, full decoding, and a passing `ending visual continuity` check.
- [ ] Run `npm run remotion:smoke`; verify the Polish motion graphic renders,
      audio is complete, and both VLC and Windows Media Player play it smoothly.
- [ ] Confirm Stage 2 produced `motion-plan.json` and preview/final share the
      approved visual structure.
- [ ] Hash the source before and after and confirm it is unchanged.

Record the Windows version, WSL distribution, `codex --version`, doctor JSON, and checklist result in the release notes.

## Native Windows agent, WSL2 engine

Run these from a native PowerShell (not inside WSL), after `bootstrap.sh` and
`python3 scripts/install_skills.py` inside WSL.

- [ ] `Get-Command wsl.exe -All` lists more than one `wsl.exe`, and
      `.\scripts\windows\social-video-agent.ps1 doctor` still runs.
- [ ] `.\scripts\windows\social-video-agent.ps1 doctor` runs the engine's
      `doctor` (not "distribution 'doctor' is not installed") and its
      `runtime mode` line reads `windows-agent-wsl-runtime`.
- [ ] `echo $env:PATH` inside `wsl.exe -d <distro> --exec /usr/bin/printenv PATH`
      does not contain `~/.local/bin`, and the adapter still finds the engine
      with no `/usr/local/bin/social-video-agent` link present.
- [ ] `Get-Item "$HOME\.agents\skills\social-video-agent"` shows no `LinkType`,
      and `Get-Content "$HOME\.agents\skills\social-video-agent\SKILL.md"`
      prints the skill.
- [ ] `.\scripts\windows\social-video-agent.ps1 workflow init
      "C:\Users\Test User\Videos\Mój film (2026) $x.mp4" --project-root
      "C:\Users\Test User\projekt"` starts, and `edit\runtime.json` records
      `"runtime_mode": "windows-agent-wsl-runtime"` and `"agent_platform": "win32"`.
- [ ] With two WSL 2 distributions and no default, the adapter stops with
      `no_distribution`; `-Distribution <name>` runs in exactly that one.
- [ ] `Get-Command ffmpeg, node, python -ErrorAction SilentlyContinue` on the
      Windows side is not what the run used: every media step ran in WSL.
