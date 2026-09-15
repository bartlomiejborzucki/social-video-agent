# Upstream

This project began from **[browser-use/video-use](https://github.com/browser-use/video-use)**
and remains substantially indebted to it.

```bash
git remote -v
# origin     <this project>
# upstream   https://github.com/browser-use/video-use.git
```

**Forked from / reviewed at:** `9575612f066aa517354790a645fd90f9f95a743b`
**Upstream licence:** MIT, Copyright (c) 2026 Browser Use — retained in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [NOTICE](NOTICE).

## What this means in practice

video-use worked out the architecture this project uses: a coding agent reasons
over a compact transcript, writes an explicit edit decision list, and
deterministic local tools render it, with the agent then inspecting its own
output. That idea is theirs. We did not invent it and we do not claim to have.

What we changed is what runs inside that shape. The reasoning is in
[docs/architecture/ADR-001-video-use-relationship.md](docs/architecture/ADR-001-video-use-relationship.md);
the full audit that produced it is in
[docs/research/video-use-audit.md](docs/research/video-use-audit.md).

| | |
|---|---|
| **Substantially based on upstream** | The pipeline shape and editorial doctrine. Frame-rate parsing and selection, rotation handling, the HDR tone-map chain, loudness targets, cut fades, and phrase grouping — ported function by function, cited in code and in [provenance](docs/research/provenance.md). |
| **Modified** | Phrase packing (length cap, interior word offsets, true media duration). Rotation handling (returns an angle; raises rather than assuming landscape). Cut fades (clamped for very short ranges). Caption margins (resolution independent). |
| **New here** | Local transcription and the provider protocol. Content-addressed caching. Ten validated artifact schemas. Single-pass rendering. Vertical reframing with zero-phase smoothing. ASS captions. Mechanical QA. `doctor`. Profiles as configuration. Cross-agent skill packaging. |
| **Not carried over** | ElevenLabs-only transcription, the filename-based cache, the encode-concat-re-encode architecture, the frozen caption style, the unvalidated EDL, prompt-only self-evaluation, the vendored Manim skill. |

Other projects that influenced the design — ClipsAI, claude-shorts, auto-editor,
FunClip, and the official Remotion plugin — are credited in
[provenance](docs/research/provenance.md) and assessed in
[docs/research/ecosystem-audit.md](docs/research/ecosystem-audit.md).

## Tracking upstream

`upstreams.yml` records every project we track, the commit we reviewed, and why.
A scheduled workflow compares the recorded commit against upstream's HEAD and
**opens an issue** when they differ. It never merges automatically.

```
DETECT  →  REVIEW  →  ADAPT OR IGNORE
```

The issue lists the new commits, the files they touch, the likely impact on our
divergent components, and — the point of the exercise — whether upstream may
have fixed something we are carrying a custom patch for. Carrying an unnecessary
patch is a cost; the monitor exists to notice when we can drop one.

## Contributing back

Some of our fixes are generic and belong upstream rather than here: UTF-8 file
writes, ffmpeg filter-path escaping, surfacing ffmpeg's stderr on failure,
memoising per-segment probes, and correcting the caption-margin drift between
`SKILL.md` and `render.py`.

We will offer these. We also record honestly that upstream has merged roughly 9
of 87 pull requests ever opened and has declined local transcription six times,
so nothing in our roadmap assumes acceptance.

Behaviour specific to social video — vertical reframing, clip discovery,
caption styling, brand and output profiles — stays here. It is not upstream's
problem.

## Attribution policy

Attribution in `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, this file and
`docs/research/provenance.md` is permanent. It is not removed on rebrand, and
upstream code is never represented as originally ours.

Browser Use branding does not appear in user-facing output, which is a different
thing from attribution and is the reason both exist.
