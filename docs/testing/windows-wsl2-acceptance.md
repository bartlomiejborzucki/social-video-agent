# Windows 11 + Codex + WSL2 acceptance

Run this checklist on a real Windows 11 machine. Generic Linux CI does not prove `/mnt/c` behavior.

- [ ] In ChatGPT Desktop, set **Settings → Agent environment → Windows Subsystem for Linux**, select the distribution, and restart the app.
- [ ] Clone the repository to `~/projects/social-video-agent`, not `/mnt/c`.
- [ ] Run `./scripts/wsl/bootstrap.sh`.
- [ ] Confirm the Remotion license choice, initialize a workflow with
      `--remotion-license free_license_eligible` or
      `company_license_confirmed`, and verify the declaration is persisted.
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
