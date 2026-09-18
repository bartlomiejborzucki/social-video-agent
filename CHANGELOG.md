# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and semantic versioning.

## [Unreleased]

## [0.5.0] - 2026-09-18

### Added

- Optional cover and end-card plates from a cloud image model, gated on real
  credentials rather than on a subscription: OpenAI `gpt-image-1-mini` or Gemini
  `gemini-2.5-flash-image`, selected by `image status`, refused on a host with no
  image API. The model draws backgrounds only; every word is composed locally
  from the brand contract. Consent is `image_generation_policy` or
  `--allow-cloud-image`, and `visuals.json` records provider, model, the exact
  prompt, consent basis and SHA-256.
- `social-video-agent cover`: a composed cover still over a generated plate, a
  real frame, or a solid brand colour, with `cover.json` provenance, plus a
  `--cover` delivery variant. `--poster` remains the raw frame grab.
- `end_card` motion elements accept an `image_asset` background with
  `image_dim_pct`; no other element type may, and plates are staged into the
  private render directory like fonts and logos.
- Platform specs (`reels`, `tiktok`, `shorts`) as editable JSON, a `platforms`
  command, `target_platforms` project config, and `qa`/`deliver --platform`
  checks for estimated feed-UI safe zones, aspect ratio, hard duration limits
  and the editorial length ceiling.
- Agent-authored `publish.json` (title, description, hashtags, alt text, spoken
  hook, CTA), validated against the target platforms and carried into the
  delivery manifest with its hash.
- Opening QA: `opens on an image`, `captions start immediately`, and
  `qa/opening-contact-sheet.png`, so the hook is measured the way the ending was.
- Music beds and sound effects, making `music_policy` and `sfx_policy`
  executable instead of decorative. `audio_bed` mixes one local track under the
  edit with sidechain ducking, fades and an optional declared loop; effects are
  placed by hand at named moments with a reason, never on a timer. Both require
  `license_confirmed`, both are refused when the project policy is `none`, the
  mix runs before loudness normalisation, and brand QA checks the mix that
  happened against the policy and warns when a bed is too loud or not ducked.
- `speaker` framing is now implemented rather than falling back with a warning.
  It tracks each face across sampled frames using YuNet's mouth landmarks,
  measures mouth motion, and correlates it with the speech envelope. When no
  face is convincingly ahead of the runner-up it declines to pick and records
  the fallback in the reframe reason. This is a correlation heuristic, not
  neural ASD; LR-ASD remains the recorded next step.
- `shorts list` and `shorts create`: the mechanical half of turning one long
  recording into several standalone clips. Each selected candidate gets its own
  workspace, single-range EDL and a copy of the parent's transcripts, so nothing
  is ever re-transcribed per clip. Selection stays editorial: an unreviewed
  candidate set produces nothing, and anything under three seconds is refused.

### Fixed

- The default Remotion renderer silently dropped the contracted active-word
  caption highlight: word timings were excluded from its props, so the
  `bold-caption` contract rendered as flat text while brand QA passed. Remotion
  now draws the highlight, applies the contract's case per word as the ASS
  writer does, and render manifests record the caption features actually
  applied. Brand QA fails when a contracted feature was not drawn instead of
  comparing the contract with a copy of itself.

## [0.4.0] - 2026-09-17

### Added

- Versioned project config commands and compiled `brand-contract.json` with
  deterministic Remotion caption boxes, resolved fonts/logos, exact colors,
  margins, resolution and CFR.
- Blocking brand QA, automatic structured-caption discovery, atomic
  multi-artifact editorial fixes, privacy-boundary review sheets, and a native
  Stage 5 delivery command with per-file QA and SHA-256 manifest entries.
- CLI/skill/plugin/package compatibility checks and a documented migration path.

## [0.3.0] - 2026-09-17

### Added

- Default Remotion motion-design composition for new staged workflows, with
  exact locked Node dependencies, Chrome/bootstrap/doctor checks, a validated
  `motion-plan.json`, project-aware restrained graphic primitives, and a real
  offline H.264/AAC smoke render in CI.
- A blocking Stage 0 license declaration before discovery or media work, plus
  an explicit FFmpeg-only opt-out and backwards-compatible legacy workspaces.

### Changed

- FFmpeg remains responsible for deterministic cuts, captions, audio timing and
  the base edit; Remotion composites the planned visual layer; FFmpeg/ffprobe
  still provide blocking technical QA and full-stream decode validation.

## [0.2.1] - 2026-09-17

### Fixed

- Show persisted OpenAI and Claude model recommendations at every guided
  boundary, including Stage 4 finalization and Stage 5 delivery, while keeping
  version 1 workflow states resumable.

## [0.2.0] - 2026-09-17

### Added

- WSL2-first bootstrap, diagnostics, path normalization, plugin marketplace, release checks, and acceptance documentation.
- Blocking timestamp/CFR/duration QA, atomic stable render artifacts, explicit
  split A/V and privacy-safe ending strategies, editorial QA handoff, and
  repeated-frame continuity analysis for the final ten seconds.
- Bounded target-project discovery with cached, source-traceable context;
  optional project configuration; and Unicode-safe asset discovery.
- Persistent guided/continuous workflow state, budget-aware conceptual model
  tiers, validated stage handoffs, status/resume commands, and progressive
  skill references for multi-model editing.

## [0.1.0] - 2026-09-16

- Initial public alpha of the local transcript-first social video editor.
