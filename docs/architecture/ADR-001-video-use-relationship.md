# ADR-001: Relationship to browser-use/video-use

**Status** Accepted
**Date** 2026-09-15
**Context reviewed at** upstream `9575612`

## Context

This project starts from `browser-use/video-use`, and we had to choose how to
relate to it:

- **A.** A maintained fork.
- **B.** A project importing video-use as a dependency.
- **C.** A thin extension layer around video-use.
- **D.** A hybrid: retain selected components, diverge on architecture.

The goal is to minimise duplicated maintenance while being able to fix what is
broken and add what is missing for social video.

## What the audit established

**B is not possible.** `pyproject.toml` declares `py-modules = []` and no
`packages`. `pip install` produces an empty distribution. There is nothing to
import. The five helpers are standalone scripts invoked as
`python helpers/<name>.py`.

**C is not possible.** There are no extension points: no plugin interface, no
registry, no configuration surface beyond a handful of CLI flags. Every gap we
must close — transcription provider, caching, captions, reframing, encoding
correctness, EDL validation — lives *inside* those five scripts. Extending
without modifying is not available.

**A is unattractive.** Upstream has merged roughly 9 of 87 pull requests ever
opened, with 78 open at review. Local transcription has been proposed six times
and merged zero. Around sixteen separate Windows-correctness fixes sit unmerged,
as does the preflight command its own issue #121 asks for. A tracking fork would
accumulate permanent divergence with no realistic path to upstreaming it, and
would inherit a codebase whose error handling discards every ffmpeg diagnostic.

The corollary is that upstream moves slowly, so *tracking* it is cheap even
though *merging into* it is not.

## Decision

**Option D.** A new installable Python package that keeps video-use's
architecture and editorial doctrine, and ports its hard-won logic
function-by-function with file-and-line attribution.

Concretely:

1. `browser-use/video-use` is configured as the `upstream` git remote and
   tracked in `upstreams.yml`, monitored by CI.
2. Specific, well-tested upstream functions are ported with attribution in code
   comments and in `docs/research/provenance.md`.
3. The conceptual pipeline is unchanged. The implementation inside it is ours.
4. The original MIT notice is retained in `THIRD_PARTY_NOTICES.md` and `NOTICE`.
5. Generic fixes are offered upstream on a best-effort basis; nothing in our
   roadmap depends on them being accepted.

## Consequences

**Good.** We can fix the encoding, escaping, error-reporting and architectural
defects without fighting a merge boundary. We ship a real package with a CLI,
schemas, and tests. Transcription works with no API key. The render is one pass
rather than encode-concat-re-encode.

**Costs.** We carry our own maintenance. Upstream improvements must be reviewed
and adapted rather than merged, which is what the upstream monitor is for.

**Obligation.** Because a meaningful amount of upstream thinking and some
upstream code survives here, attribution is not optional and is never removed
from the licence and provenance files. Where upstream's approach is better than
a change we contemplate, we keep upstream's.

## Alternatives, briefly

Rewriting from scratch without reference to video-use was rejected: it is
precisely the outcome the audit warns against. The transcript-first architecture,
the packed transcript, word-boundary cuts, the 30 ms fade, the tone-map chain and
the fps handling are all good work, and replacing them with our own versions
would cost effort and lose correctness for no benefit.
