# Ecosystem audit

All entries reviewed **2026-09-15** against the then-current default branch.
Judgement is on architecture, code quality, maintenance, licence and fit —
popularity is evidence of interest, not correctness, and several of the most
starred projects here are the least usable.

Verdict key: **depend** · **adapt** (port code under its licence) ·
**reimplement** (take the concept, write our own) · **inspiration** · **skip**

---

## Depend on

### SYSTRAN/faster-whisper — MIT
Last release 1.2.1; last commit on master 2025-11-19.
Our default ASR. No PyTorch, ungated models, CPU-viable, real per-word
timestamps via `word_timestamps=True`, Silero VAD built in. Dependencies are
light: ctranslate2, huggingface_hub, tokenizers, onnxruntime, av, tqdm.
*Weakness:* ~10 months without a commit on master. Not abandoned — SYSTRAN-backed
with enormous downstream use — but worth watching. `whisper.cpp` is the fallback.
*Gotcha we hit:* a visible CUDA device is not a usable one. CTranslate2 loads a
CUDA model happily and only discovers a missing cuBLAS when it runs the encoder,
so the fallback has to wrap decoding, not construction. **Verdict: depend.**

### Breakthrough/PySceneDetect — BSD-3-Clause
0.7.1, actively maintained since 2014, last commit 2026-09-12.
Best-in-class and trivially light: the core declares only numpy. One-line API.
*Gotcha:* use the `scenedetect-headless` distribution on servers; do **not**
depend on `scenedetect-core`, which was published briefly and yanked.
**Verdict: depend.** Scene cuts are the skeleton reframing snaps to.

### OpenCV YuNet — Apache-2.0 (model and code)
`cv2.FaceDetectorYN`, model from opencv_zoo, 233 KB, ungated, no separate
install. Substantially better than the Haar cascades most open-source reframers
still use, and far lighter than MTCNN. **Verdict: depend.**

### m-bain/whisperX — BSD-2-Clause, optional extra only
3.8.6, last commit 2026-07-13.
Licence is clean at current HEAD: it imports faster-whisper rather than vendoring
OpenAI Whisper. wav2vec2 forced alignment gives tighter word timings than
Whisper's DTW, and **needs no Hugging Face token**. Its `IntervalTree` for
speaker-to-word assignment is genuinely good.
*Cost:* torch, torchaudio, torchvision, torchcodec — realistically 5–8 GB, and
`torchcodec` has no Linux-aarch64 wheels. Requires Python < 3.14.
**Verdict: depend, behind the `[align]` extra. Never on the default path.**

---

## Adapt (port code under its licence)

### ClipsAI/clipsai — MIT, **abandoned**
Last commit 2024-01-17; PyPI frozen at 0.2.1 (2024-01-15); `import clipsai` is
broken out of the box because its declared dependencies omit whisperx, which the
code imports. It will not install alongside a 2026 torch stack.
The *architecture* is the valuable part and we adopted it: crop is
**piecewise-constant per segment**, not tracked per frame, with segments bounded
by scene cuts snapped against speaker turns (0.25 s threshold), and adjacent
segments merged when their positions differ by under 4% of the frame.
Discarded: MTCNN + KMeans-over-bounding-boxes as an identity tracker, and
mouth-aspect-ratio as a speaking proxy computed from 13 random samples.
*Defect we did not reproduce:* `_calc_crop` clamps only the low side, so the crop
window can run off the right or bottom edge. We clamp both.
**Verdict: adapt architecture and the dead-zone idea. Do not depend.**

### AgriciDaniel/claude-shorts — MIT
Last commit on `main` 2026-04-10. The closest thing to this product in the audit.
Light dependencies (faster-whisper, mediapipe, opencv), no paid API.
Adopted: the crop plan as a JSON contract — `{strategy, crop, crop_keyframes,
output_resolution}` — and **keyframe deduplication by percentage of crop width**,
which is the right resolution-independent formulation.
Not adopted: its renderer is Remotion (see licensing below); its face path
samples five frames for a whole clip, picks the largest face rather than the
speaking one, ignores `y` entirely, and produces a static crop with no smoothing.
**Verdict: adapt the contract and the dedup rule.**

### WyattBlue/auto-editor — The Unlicense (public domain)
Last commit 2026-09-13. The best-maintained project in this audit.
Now a **Nim binary**, not an importable Python library. Its `v3` timeline format
is well specified and round-trips to Premiere, Resolve, Final Cut, ShotCut and
Kdenlive. Its label/action model (`--edit:N`, `--when:N`) is an elegant
generalisation of "cut silence".
We kept our own EDL as canonical — `v3` has no slot for reason, beat, speaker,
reframe, captions or brand — and note v3 export as a future path to free NLE
interchange. Its four Claude Code skills are the best model in this audit for
writing a CLI-wrapping skill, and we followed their style.
**Verdict: adapt the format later; copy the documentation style now.**

---

## Reimplement the concept

### modelscope/FunClip — MIT code, Apache-2.0 default models
Last commit 2026-09-10, actively maintained, and unusually honest about model
licences. The idea worth taking is the interaction model: **the transcript is the
timeline, and selecting text selects video.** That is exactly right for an
agent-native editor.
Not taken: the FunASR stack is heavy, Chinese-first, and duplicates
faster-whisper; it pins `moviepy==1.0.3` and bundles `g4f`, a GPT-scraping
library we would not ship. **Verdict: reimplement the concept.**

---

## Gated, optional, or a trap

### pyannote/pyannote-audio — MIT code, **gated weights**
Last commit 2026-06-30.
The code is MIT, but `pyannote/speaker-diarization-community-1` requires a Hugging
Face account, click-through acceptance of user conditions, and a read token. The
weights cannot be redistributed and a shared token would violate the terms. This
breaks headless, air-gapped and enterprise-proxied installs.
Also note `speaker-diarization-precision-2` is a **paid hosted API behind the same
`from_pretrained` call** — easy to invoke by accident.
whisperX's VAD uses a pyannote checkpoint vendored in-repo and needs no token;
only full diarization is gated.
**Verdict: optional extra, user supplies their own token, never a default.** For a
single-speaker-dominant editor, on-screen face detection answers the question
diarization would.

### Remotion — **not open source**
`remotion-dev/skills` carries no LICENSE and is `"private": true`; the upstream
`LICENSE.md` grants free use only to individuals, non-profits, organisations with
**up to 3 employees**, and evaluation. Larger for-profit organisations must buy a
company licence.
Consequence: the entire core pipeline here is FFmpeg and libass, which are fully
open. Remotion is a possible opt-in future layer for motion graphics only, and the
obligation is stated plainly in the README. Users at companies above the threshold
must check with their own legal team before enabling it.
Its official plugin skills (20–70 lines each, split by topic) are the current
best-practice reference for skill structure, and we followed that shape rather
than upstream video-use's single 23 KB file. We link users to the official plugin
rather than duplicating its knowledge base.
**Verdict: optional, never required, never vendored.**

### xixihhhh/hotclip — **AGPL-3.0**
Last commit 2026-09-12. Architecturally the closest competitor: TypeScript,
YuNet-based reframing, an MCP server, a skill, and real tests. Copyleft makes it
unusable for us. We reached the same conclusion it did about YuNet independently.
**Verdict: competitive intel only. Do not port.**

---

## Skip

| project | licence | why |
|---|---|---|
| `Anil-matcha/AI-Youtube-Shorts-Generator` | MIT | Rewritten into a funnel for a paid API; `requirements.txt` is now `requests` + `python-dotenv`. The local fallback is Haar cascades. Nothing to take. |
| `RayVentura/ShortGPT` | MIT | Abandoned (last commit 2025-02-10). Requires OpenAI, ElevenLabs and Pexels. Depends on `tinymongo`, itself unmaintained. |
| `harry0703/MoneyPrinterTurbo` | MIT | Active and popular, but solves a different problem: generating faceless videos from a topic. No transcript-driven editing, no reframing. |
| `KyaniteLabs/kinocut` | Apache-2.0 | 623 Python files, 201 MCP tools, an SEO-stuffed README. Good concepts (provenance receipts, preflight gates) buried in unusable surface area; its scene detection is perceptual-hash based and weaker than PySceneDetect. **Inspiration only.** |
| `ayushozha/AdobePremiereProMCP` | MIT | 1,027 tools. Almost certainly generated. |
| `x777/frontstage` | GPL-3.0 | Copyleft. |
| `limmsyd/short-form-vibe-edit` | — | **Does not exist (404).** |
| `haidrrrry/claude-remotion-skills` | — | **Does not exist (404).** The real repo is `claude-remotion-skill`, singular, and inherits the Remotion licence. |
| The 2026 "long video → shorts" cohort | various | `AutoClipAi`, `ai-shorts-agent`, `stream-to-shorts` and similar: days old, no tests, grandiose READMEs. |

---

## Worth revisiting

### Active-speaker detection — the real gap
Every project surveyed reframes with no face detection, Haar cascades, MTCNN plus
a mouth-aspect-ratio heuristic, or an average of five sampled positions. **None**
combines genuine speaker-aware detection with scene-cut snapping, temporal
smoothing and hysteresis.

We implement the latter three now; genuine ASD is the next step.
- `Junhua-Liao/LR-ASD` (MIT, last commit 2025-03-23) — ~1M parameters, realtime
  on CPU, near-TalkNet accuracy. Best technical choice.
- `sieve-community/fast-asd` (MIT) — its `talknet/` subdirectory is standalone and
  handles variable frame rates, which the original TalkNet does not. The rest of
  the repo calls a hosted API; take only that subdirectory.
- Research forks (`LoCoNet_ASD`, `SPELL`, `UniTalk-ASD`) mostly carry **no
  licence** and are legally unusable.

### Cassette-Editor/oh-my-cassette — MIT
The only project shipping `.claude-plugin/`, `.codex-plugin/`, `.agents/skills/`
and a root `.mcp.json` side by side. We followed its directory layout. The
product itself is a thin client for a hosted service.

### AH64-dll/OpenEdit — MIT
Renders via MLT/melt rather than Remotion — a credible open alternative if we
ever need a compositor beyond FFmpeg. Worth a second look.
