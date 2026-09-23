# Third-party notices

This project incorporates or depends on the work below. Licences are reproduced
or cited as their terms require. Per-item detail of what was taken and how much
is in [docs/research/provenance.md](docs/research/provenance.md).

---

## Code adapted into this project

### browser-use/video-use

Portions of this project are derived from `browser-use/video-use`
(https://github.com/browser-use/video-use), reviewed at commit `9575612`.
Adapted functions are identified in source comments and in the provenance
document.

```
MIT License

Copyright (c) 2026 Browser Use

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Design influences (no code copied)

- **ClipsAI/clipsai** — MIT, Copyright (c) 2023 Clips AI, Inc.
  Segment-based crop architecture and the spatial dead zone.
- **AgriciDaniel/claude-shorts** — MIT.
  The crop-plan JSON contract and keyframe deduplication by percentage of crop
  width.
- **WyattBlue/auto-editor** — The Unlicense.
  Skill documentation style; `v3` timeline format recorded as a future export
  target.
- **parleyw/video-use** — the `validate_setup()` lifecycle idea only. See the
  provenance document for why none of its code was adopted.

---

## Runtime dependencies

| package | licence |
|---|---|
| faster-whisper | MIT |
| CTranslate2 | MIT |
| PySceneDetect (`scenedetect-headless`) | BSD-3-Clause |
| OpenCV (`opencv-python-headless`) | Apache-2.0 |
| NumPy | BSD-3-Clause |
| Pillow | MIT-CMU |
| fontTools | MIT |
| Pydantic | MIT |
| Typer | MIT |
| Rich | MIT |

### Optional extras

| package | extra | licence | note |
|---|---|---|---|
| WhisperX | `align` | BSD-2-Clause | Pulls the PyTorch stack. |
| pyannote.audio | `diarize` | MIT **code** | See model licensing below. |
| yt-dlp | `fetch` | The Unlicense | Downloading is subject to each site's terms and to copyright; `fetch` requires the user's own rights statement. |

---

## Models

Model weights are licensed separately from the code that runs them. This
distinction is frequently blurred; it is stated explicitly here.

| model | licence | gated? |
|---|---|---|
| Whisper (faster-whisper CTranslate2 conversions) | MIT | No. Downloaded on first use. |
| YuNet face detection (OpenCV Zoo) | Apache-2.0 | No. 233 KB, fetched on first use. |
| Silero VAD (bundled with faster-whisper) | MIT | No. |
| wav2vec2 alignment models (WhisperX) | varies by model; the torchaudio defaults are permissive | No token required. |
| `pyannote/speaker-diarization-community-1` | **Gated** | **Yes.** Requires a Hugging Face account, acceptance of the model's user conditions, and a personal read token. We cannot redistribute these weights or supply a token. |

`pyannote/speaker-diarization-precision-2` is a **paid hosted service** reached
through the same `from_pretrained` call as the open pipeline. Selecting it sends
audio to a third party.

---

## External tools

**FFmpeg** is required and is not bundled. Depending on how it is built, FFmpeg
is licensed under LGPL-2.1+ or GPL-2.0+. `social-video-agent doctor --install-ffmpeg`
downloads a build from BtbN/FFmpeg-Builds **into a user cache directory at the
user's request**; no FFmpeg binary is redistributed in this repository or in any
package we publish.

---

## Remotion

**Remotion is not open-source software.** Under its licence, free use is limited
to individuals, non-profit organisations, for-profit organisations with **up to
three employees**, and evaluation. Larger for-profit organisations require a paid
company licence from https://remotion.pro.

No Remotion code is vendored in the Python package. The wheel carries only this
project's compositions, render script, and npm manifest and lockfile. Remotion's
npm packages are pinned in `package-lock.json` and installed from the registry
on the user's machine, by the bootstrap in a checkout or by
`social-video-agent doctor --install-remotion` for an installed package. New workflows
use it as the default motion-design compositor after FFmpeg has created the
frame-accurate base edit. Stage 0 requires the user to declare free-license
eligibility or confirm a Company License before discovery or media processing.
An explicit FFmpeg-only opt-out remains available. **Confirm the current terms
at https://www.remotion.dev/license before selecting either declaration.**

---

## Fonts

No fonts are bundled. Captions use a font discovered on the host system.
Whichever font you select remains subject to its own licence, which may restrict
embedding or redistribution of rendered output in some cases.
