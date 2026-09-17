# Troubleshooting

Run `social-video-agent doctor` first. It checks ffmpeg and its libraries, Python
packages, fonts and their Unicode coverage, Node, locked Remotion packages,
Chrome Headless Shell, GPU usability, and console encoding. Every failure comes
with what to do about it.

## Common

**Brand config was discovered but the render uses defaults.** Run
`social-video-agent config validate PROJECT --workspace WORKSPACE`, recompile
Stage 2, and confirm `brand-contract.json` exists. An EDL from before 0.4 has no
contract fingerprint and must be recompiled; do not type the project name into
`brand_profile`.

**Configured font/logo is missing.** Assets resolve relative to the target
project, never the installed skill. Install the font inside WSL or set
`font_file`; fix `logo_file` when `logo_usage: required`. Ubuntu bootstrap
installs Lato and Noto Sans.

**Stage 5 output stayed temporary.** Use `social-video-agent deliver edit
--output /durable/path --with-captions`. `/tmp` is rejected. Alternatively set
an approved `delivery_output` in project config.

**No ffmpeg.** Install via the system package manager, or
`social-video-agent doctor --install-ffmpeg` to fetch a static build with no
administrator rights.

**Remotion or its browser is missing.** Keep the repository in the WSL Linux
filesystem, then rerun `./scripts/wsl/bootstrap.sh`. The bootstrap runs
`npm ci` from the lockfile and `npx remotion browser ensure`; do not put
`node_modules` under `/mnt/c`.

**Stage 0 asks about a Remotion license.** This is intentional and happens
before project/media discovery. Select `free_license_eligible` only if you have
confirmed you meet the current free-license terms, or
`company_license_confirmed` after obtaining the appropriate license. If neither
applies, the normal workflow stops. An explicit `--renderer ffmpeg` opt-out is
available for the core non-Remotion renderer.

**Remotion says `motion-plan.json` is missing.** Stage 2 has not completed its
visual plan. Create the validated artifact described in `artifacts.md`; do not
replace it with ad-hoc React edits or random effects.

**Captions do not appear.** The ffmpeg build lacks libass. `doctor` reports
this. Homebrew's formula has shipped without it.

**Captions render as empty boxes.** The font lacks those glyphs. `doctor`
reports coverage per language. Install Noto Sans.

**HDR footage looks washed out or fails.** Tone mapping needs ffmpeg built with
libzimg. `doctor` reports it; SDR sources are unaffected.

**Transcription is slow.** It runs on CPU by default. A visible CUDA device is
not necessarily a usable one — CTranslate2 needs a matching cuBLAS and cuDNN,
and transcription falls back to CPU automatically when they are missing.
`SOCIAL_VIDEO_FORCE_CPU=1` skips the attempt. Smaller models are much faster;
`base` is often enough for cutting.

**The wrong audio is transcribed.** Multi-track recordings are common — OBS puts
desktop audio on track 0 and the microphone on track 1. `inspect` lists the
tracks; use `--audio-track 1`. A silent track is refused with an explanation
rather than transcribed.

**Phone video is sideways.** Rotation metadata is read from the display matrix
and applied. `inspect` shows stored size, display size, and rotation separately.

**Cuts sound abrupt.** Cut boundaries snap to word edges and carry short fades.
If it still feels tight, raise `cut_padding` in the profile.

**VLC has no sound, Windows playback stutters, or audio bitrate is absurd.**
Re-render with the current CLI and run `social-video-agent qa WORKSPACE`. QA now
blocks nonstandard VFR output, compressed/non-monotonic AAC timestamps, wrong
AAC cadence, stream-duration mismatch, and incomplete decoding. Do not repair
the file with an external post-trim.

**The ending looks frozen.** Audio outlasts the safe moving image and the EDL
lacks a suitable visual ending. Choose a second approved B-roll shot, adjust
its timing, use an approved return shot, trim only at an edit-plan-approved
sentence boundary, or provide a designed end card. A sub-0.75-second hold may
be declared explicitly. Longer holds need supervising-editor approval and a
reason; automatic zooms, loops, and synthetic motion are not fixes.

**The edit feels over-cut.** Use a more restrained profile (`calm-expert`), or
raise `max_pause` and `min_pause`. The mechanical pass only removes dead air,
isolated filler, and repeated phrases — everything else was your decision.

## Platform notes

- **Windows + Codex**: select WSL2 as the agent environment. The CLI accepts
  pasted drive-letter paths and converts them with `wslpath`; it never invokes
  Windows-side Python or `ffmpeg.exe`.
- **WSL2**: keep the repository and intermediates under `~`. Media may stay on
  `/mnt/c`; the default workspace then moves high-I/O work into the Linux cache.
- **macOS**: check the ffmpeg build includes libass.
