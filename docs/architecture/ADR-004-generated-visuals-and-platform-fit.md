# ADR-004: Generated visuals, composed covers, and platform fit

Status: accepted, 2026-09-18.

## Context

The pipeline produced a correct edit and then handed over a raw frame grab as
the cover. For a short, the cover and the first second are where most of the
audience decision happens, and neither was designed or measured. Users also
asked to use the image generation available through their assistant
subscriptions for a cover or end card.

Three facts constrained the design:

1. A ChatGPT or Gemini subscription is not API access. The ChatGPT app generates
   images; the Images API is billed separately on an API key. Neither Codex CLI
   nor Gemini CLI exposes an image tool. Anthropic has no image-generation API at
   all, so on a Claude host the feature cannot exist.
2. Image models render text badly, especially Polish diacritics, and cannot
   honour a compiled brand contract.
3. The project's own invariant is that nothing leaves the machine without
   explicit configuration.

## Decision

**Detect on credentials, not on hosts.** `detect_image_provider` resolves a
provider from `OPENAI_API_KEY` or `GEMINI_API_KEY`/`GOOGLE_API_KEY`, with the
host used only to break ties and to write an actionable diagnostic. Gemini wins
a tie because its free tier can cost nothing. The feature is absent, with a
reason, when no key is present.

**The image model draws backgrounds only.** The guardrail prompt bans text,
logos and faces. Titles, end-card copy, logo placement and typography are drawn
locally from `brand-contract.json`. This keeps brand QA meaningful and keeps
covers correct in any language.

**Covers are composed with Pillow, not Remotion.** A cover is a still; composing
it locally keeps it available on the FFmpeg-only route, costs no browser render,
and is reproducible. Remotion remains the video compositor, and gained only an
`end_card` image layer.

**Consent is a named basis.** `image_generation_policy` in the project config or
an explicit `--allow-cloud-image`, recorded in `visuals.json` alongside the
provider, model, exact prompt and hash. Absence of a policy is not consent.

**Platform fit is data, and warnings name the numbers.** Reserved feed-UI zones
are conservative estimates in editable JSON. Hard duration limits are errors;
the editorial ceiling and safe-zone overlaps are warnings that report both the
measured and expected value.

**Publishing copy is authored, not generated.** `publish.json` is written by the
agent and validated by the CLI. Generating titles and hashtags in code would
invent content the user never approved.

## Consequences

- On a Claude host the cover route still works; only plates are unavailable.
- A user who wants plates pays their own provider, and the per-image cost is
  stated before the call.
- Brand QA now compares contract against renderer evidence rather than against a
  copy of the contract, which is what surfaced the dropped Remotion active-word
  highlight this release fixes.
- Reserved-zone estimates will drift as platforms change their UI. They are JSON
  so that correcting them is a data edit, not a release.
