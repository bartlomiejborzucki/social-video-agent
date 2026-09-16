# Troubleshooting

Run `social-video-agent doctor` first. It checks ffmpeg and its libraries, Python
packages, fonts and their Unicode coverage, GPU usability, and console
encoding, and every failure comes with what to do about it.

## Common

**No ffmpeg.** Install via the system package manager, or
`social-video-agent doctor --install-ffmpeg` to fetch a static build with no
administrator rights.

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
