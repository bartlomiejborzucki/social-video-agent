# Windows 11 + Codex + WSL2 acceptance

Run this checklist on a real Windows 11 machine. Generic Linux CI does not prove `/mnt/c` behavior.

- [ ] In ChatGPT Desktop, set **Settings → Agent environment → Windows Subsystem for Linux**, select the distribution, and restart the app.
- [ ] Clone the repository to `~/projects/social-video-agent`, not `/mnt/c`.
- [ ] Run `./scripts/wsl/bootstrap.sh`.
- [ ] Run `social-video-agent doctor`; the final summary is `READY`.
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
- [ ] If Remotion is enabled in a future release, run its WSL smoke render; it is not enabled in v0.1.0.
- [ ] Hash the source before and after and confirm it is unchanged.

Record the Windows version, WSL distribution, `codex --version`, doctor JSON, and checklist result in the release notes.
