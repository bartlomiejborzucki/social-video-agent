# ADR-005: Claude Motion as a source of designed segments

**Status:** accepted, implemented in 1.6

**Date:** 2026-10-12, revised 2026-10-13

## Context

Claude Motion is an Anthropic artifact type, in beta on Team and Enterprise
plans since 2026-10-08. A Claude session writes a *film* through its artifact
tools: a store of documents (`film/meta`, `film/script`, `modules/scenes.json`,
`modules/base.css`, one JavaScript module per scene) in which everything on
screen is a pure function of time. Images, fonts and muted video clips are
uploaded to the film as assets. The user scrubs the film, comments on moments,
and exports an MP4 from the film's page.

Five facts constrain any integration:

1. **Only a Claude session can write a film.** The Python CLI cannot, and Codex
   has no such tool. The project is Codex-first with Claude as the alternative
   route, so the feature must be optional and degrade to what exists today.
2. **Export is manual and happens in the browser.** There is no CLI or API
   export, and the type's own rules forbid the agent from producing a video
   file. The exported MP4 cannot be reproduced from the workspace.
3. **The export is opaque and mute.** Video clips play as muted picture; there
   is no alpha channel to lay a partial graphic over the recording.
4. **One film has one size.** The default stage is 1920×1080; a film declares
   its own `width`, `height` and `fps` in `modules/scenes.json`, vertical
   1080×1920 included, at 24, 30 or 60 fps. Another aspect ratio is a second
   film.
5. **Uploading the recording is uploading media.** AGENTS.md forbids that
   without explicit, recorded consent, and no such policy exists.

Remotion already draws every graphic in the vocabulary from the brand
contract, and its authoring model (frames as a function of time) is the same
as Motion's. What Remotion does not give is a designed hook or end card on the
FFmpeg route, which users who cannot make a licence declaration take, nor a
review loop the user can scrub and comment on.

## Decision

**Motion supplies full-frame segments; it is not a renderer.** FFmpeg still
owns the timeline, Remotion the rest of the visual layer, and ffprobe the QA.
The CLI never calls Motion.

1. **Spec, on any host.** `motion film spec -w WORKSPACE --scene hook_card
   [--scene end_card ...]` writes `exports/motion-film/<edl>/`:
   - `film-spec.json`: the stage at the contract's output size, the EDL frame
     rate, each scene's absolute start and duration from `motion-plan.json`,
     its text and items, the caption band and the platform reserved zones in
     pixels, and a `spec_sha256`;
   - `base.css`: custom properties from the contract (accent, text and
     background colours, font family, safe margins);
   - `scenes.json` in Motion's own shape: the contract's output size, the
     film's frame rate, the brand background, the font slots, and one scene
     per element in timeline order, each with a stable id, a name and its
     duration in seconds.

   Only full-frame types are accepted (`hook_card`, `chapter`, `cta`,
   `quote`, `end_card`). A `lower_third` or `callout` is refused:
   an opaque export cannot be partial. A scene under one second is refused,
   because Motion refuses it. The film's frame rate is the EDL's when that is
   24, 30 or 60, otherwise 60, and the import conforms it.

   The contract font goes into a font slot by its Google Fonts family name. The
   type's ten built-in faces have no Polish letters, so a Polish film always
   names a Google family that has them, never a built-in face.

2. **Authoring, on a Claude host with Motion.** A new reference,
   `references/motion-film.md`, tells the session to create one film per spec
   at the contract's stage size, put no captions in the film, and then stop and
   ask the user to export and hand over the file's path. Without Motion the
   session says so and the Remotion graphic stays.

   The logo and the brand font file are brand files, and AGENTS.md allows no
   brand-file upload without explicit consent. They are uploaded to the film
   only under a recorded basis: a `brand_asset_upload` project policy or a
   one-off `--allow-brand-upload` on `motion film spec`, written into the spec
   and the registry. Without it the film carries no logo, and a brand font that
   is not a Google family cannot be matched, so brand QA fails that segment
   rather than accepting a substitute.

3. **Import.** `motion film import FILE -w WORKSPACE --film-id ID
   --font-used FAMILY [--scene SCENE ...]`. One export holds every scene of the
   film back to back, so the import cuts it apart:
   - probes the file with ffprobe only, as untrusted input;
   - refuses a stage that is not the contract's output size, and a length
     that differs from the sum of the spec's scene durations by more than one
     frame;
   - cuts each scene at its offset in `scenes.json` order (all of them, or
     those named), transcodes it to H.264/yuv420p at the EDL frame rate, and
     copies it into `assets/motion/` with its hash;
   - records the import in `motion-films.json`, mirroring `visuals.json`:
     film id, scene, spec hash, source and workspace paths, file hash, probe
     facts, start time, `exported_by: user`, font evidence and the replaced
     motion-plan element;
   - follows `accept_broll`: an `Overlay` with `kind: motion_film` at full
     frame, de-duplicated and validated with the EDL. Every scene, the end card
     included, is an overlay at its graphic's own time. The EDL's `END_CARD`
     fill strategy covers picture missing under speech, not a designed card,
     so it is not used;
   - removes the matching element from `motion-plan.json` so nothing is drawn
     twice. `motion film remove SCENE` restores it.

4. **Evidence and QA.** The render manifest records the film segments it
   actually composited. Brand QA fails on a hash, size or frame-rate mismatch,
   or when the recorded font is not the contract's; it warns when the brand
   contract changed after the spec was written, and when less than 60% of the
   segment's sampled pixels lie near a brand colour, naming the measured
   share. The motion sheet includes film segments.
   `workflow status` lists specs not yet imported, so a resumed session knows
   what it waits for. A render whose registered film file is missing fails with
   the film id, never drops the overlay.

5. **Host awareness.** The spec records `claude_motion` as the agent saw it in
   its own tool list (`--claude-motion`), session-scoped like the native image
   tool and never inferred from a subscription; `unavailable` refuses the
   spec. Model routing is
   unchanged: the film is authored in the Stage 2 session, and a handoff to an
   OpenAI model must not depend on it. The Remotion licence gate is unchanged.

## Alternatives rejected

- **Finish in Motion** (export the edit as a film for the user to complete):
  the film is mute, captions would be redrawn outside the contract, and
  nothing can be verified before or after a manual export, which breaks the
  Stage 4 and 5 guarantees.
- **Chroma or luma key** to lay partial graphics over the recording: 4:2:0
  H.264 fringes anti-aliased text, and the result cannot be checked against
  the brand.
- **Motion as the whole composite**, with the base render uploaded as a clip:
  uploads the user's media, needs an audio re-mux, and cannot be re-rendered
  locally. Kept under consideration on the roadmap, behind its own ADR and a
  media-upload policy.
- **No integration:** leaves the FFmpeg route without designed hook and end
  cards, and gives Claude users no review loop they can scrub and comment on.

## Verification against the live type

Read from the Motion type's own reference on 2026-10-12 (`film-api.md`,
`rough-cut.md`, `render-offline.md`):

- **Vertical is supported.** `width` and `height` are integers up to 4096;
  the reference names 1080×1920 for Reels, TikTok and Shorts.
- **Time is seconds.** A scene's `render(t)` gets seconds since the scene
  began; `dur` is seconds; scenes play back to back and their durations add up
  to the film; no scene is shorter than a second; a film is at most 300 s.
- **Frame rate** is 24, 30 or 60.
- **Fonts** are a Google family by name, fetched by the player, or font files
  uploaded as assets and named by file stem. The ten built-in faces cover
  Western European letters only.
- **Stills can be rendered without the page open.** The player has a headless
  entry (`#tools`, `window.__animation.frame(t)`) driven by Playwright and
  Chromium, deterministic and with no network. A video file still comes only
  from Export on the film's page.
- **Reserved zones** in the type's guidance: Reels and TikTok draw over about
  the top 250, bottom 420 and right 120 px; Shorts over the bottom 670 px.
  The spec carries the project's own platform data; 1.7 compares the two.

Still open, and needing one real export before the import tolerances are set:
the container, codec, pixel format and audio stream of the exported MP4, and
whether its frame rate and length match `scenes.json` exactly.

## Consequences

- An imported film file is the artifact of record. A workspace that lost it
  cannot re-render that segment, and says so.
- Text position inside a film is attested by the spec and reviewed on the
  motion sheet, not measured; consistent with safe zones being estimates.
  Because the player renders stills headlessly, 1.7 may render the film's
  frames locally before export, given the film's files.
- A full-frame card hides the speaker for its duration; the spec states each
  scene's length so the review can judge whether that costs the opening.
- Codex users see no change. Claude users without Team or Enterprise see no
  change.
- Uploading the recording stays out of scope until a policy records consent
  for it. Brand files go up only under the recorded basis above.
