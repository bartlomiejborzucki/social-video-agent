# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and semantic versioning.

## [Unreleased]

## [1.0.0] - 2026-09-23

### Added

- An installed wheel can render with Remotion. The wheel now carries the
  compositor sources (never Remotion's own packages), and
  `social-video-agent doctor --install-remotion` installs the locked npm
  dependencies and headless browser into the app cache. Until now the default
  renderer only worked from a repository checkout.
- `docs/ROADMAP.md`.
- CI tests Python 3.10 through 3.13, type-checks the 3.10 floor in its own
  environment, reports branch coverage, and lints the PowerShell adapter with
  PSScriptAnalyzer. Property tests generate Windows, WSL mount and UNC paths
  the example tests never listed.

- `caption_style` in the project config gains `active_word_highlight`,
  `highlight_color`, `emphasis_words` and `emphasis_color`. Brand keywords are
  coloured by both renderers, and brand QA fails a render that was asked for
  emphasis and did not draw it.
- `cuts find` lists hesitations, doubled words, restarted phrases and long
  pauses, each with an id, a confidence and the quoted words; `cuts accept`
  turns the chosen ones into plan drops. `compile` builds `edl.json` from the
  plan and removes accepted cuts exactly, after word snapping, even inside kept
  spans. It refuses to overwrite an existing EDL without `--force`.
- `--backend whisperx` (the `align` extra) aligns every word with WhisperX after
  faster-whisper recognises it; words it cannot place keep their timing.
- `transcribe --diarize` (the `diarize` extra and your own `HF_TOKEN`) labels
  every word with its speaker using the pinned free pyannote weights. Speaker
  reframing then follows diarized turns and cuts between faces at turn changes.
- `split_stack` layouts: two or three source regions stacked as bands, each
  `cover` or `contain`, for two speakers or a screen above the presenter. With
  `split_stack` as the default reframe, two people in shot get a pane each.
- `export WORKSPACE` writes the cut as FCPXML, Premiere/FCP7 XML,
  OpenTimelineIO and CMX 3600 EDL, frame for frame with the render, and lists
  what the formats cannot carry.
- `fetch URL --rights "..."` (the `fetch` extra) downloads one recording the
  user has the right to edit, with a provenance record beside it.
- The release workflow can publish to PyPI through trusted publishing once the
  PyPI project is configured; CI runs `twine check` on every build.
- `motion-plan.json` gains `punch_ins`: timed pushes on the picture that ease
  in, hold and ease out while captions and graphics stay put.

### Changed

- The guided route now recommends OpenAI Astra where it recommended Sol
  (Stages 1 and 3) and Sol where it recommended Terra (Stages 2 and 4); Terra
  is no longer recommended. Claude alternatives are unchanged.
- Rendering refuses any zoom above the brand's `punch_in_max`, and any punch-in
  when the project sets `punch_in_intensity: 0`.
- The transcript cache is keyed on the backend as well, so switching backends
  no longer returns another backend's transcript. Default-backend caches keep
  their names and stay valid.
- The CLI is a package with one module per command group; `social_video.cli:app`
  and `python -m social_video.cli` are unchanged, and every command's help text
  is identical.
- `render_edl` is split into input collection, loudness planning and the encode
  step.
- Every finished file is published through one atomic writer with a unique
  staging name, so two concurrent runs can no longer collide on a shared
  `.partial` file. Artifact JSON uses it too.

### Removed

- The `cloud` extra, which nothing used.

### Fixed

- Voice-cleanup measurement used its own filter-path escaping, which broke the
  filtergraph when the temp directory contained `,`, `;` or `=`. It now uses the
  shared, tested escaper.
- The Remotion bridge handed node a relative staging path while running it from
  the compositor directory; the staging root is now resolved first.
- Two transcription backends that do not exist were still being imported.
- Burned-in active-word captions lit every word not yet spoken and left spoken
  ones plain, the opposite of the Remotion route. The spoken word is now the
  highlighted one, with 1 ms colour transforms because libass ignores
  zero-length ones.
- Render manifests recorded Remotion 4.0.525 whatever was installed; they now
  record the version the compositor pins.
- `split_stack` was a declared reframe mode that rendered as a plain centre
  crop.
- Every artifact write failed on Windows: the atomic writer flushed through a
  read-only handle, which Windows refuses with `EBADF`.
- Several required `doctor` checks could fail without saying what to do.
- Registering a JPEG or WebP plate from the agent's image tool failed: Pillow
  inferred the format from the `.partial` staging name.
- EDL validation turned an unreadable source into an uncaught ffprobe error on
  its second probe; it is now a named problem, and each source is probed once.
- A Windows unit test expected a rootless output path on the cwd's drive; it is
  resolved against the project root, so it lands on the project's drive.

## [0.6.3] - 2026-09-22

### Fixed

- CI could not finish on any host but Linux. The repository-hygiene scan ran
  `git ls-files` while collecting tests, so in the container job -- where the
  workspace belongs to the runner and git runs as root, which git reads as
  dubious ownership -- one refusal aborted the entire run instead of one
  check. The job now trusts its workspace, and a checkout git cannot read
  skips rather than breaking collection.
- The caption-fit fixture asked `fc-match` for a font and inspected its return
  code, which a Windows runner never reaches: with no fontconfig the call
  itself raises, so fifteen tests errored instead of skipping.
- The Windows/WSL path tests asserted POSIX resolution of paths that only
  exist inside WSL. Resolving is native and rightly so -- on Windows a
  rootless `/mnt/d/out` lands on the current drive, and on macOS `/home`
  crosses an autofs firmlink -- so those tests are Linux-only and the path
  recognisers, which are pure string logic, still run on every host.
- A migration message was asserted verbatim against wrapped console output,
  which failed on runners whose temporary directory is long enough to push
  the sentence onto two lines.

## [0.6.2] - 2026-09-22

### Changed

- Refreshed the dependency floor and the pinned toolchain so the project builds
  on current releases: Remotion 4.0.527, React 19.3, TypeScript 7.0, and the
  matching `@types` packages; `actions/setup-node` v7 and `astral-sh/setup-uv`
  v10.2.0 in CI. The Python lock moved to current `ruff`, `urllib3`, `protobuf`,
  `filelock`, `fsspec` and `platformdirs` builds.

### Fixed

- Python 3.11+ installs silently resolved to onnxruntime 1.23 -- the last
  release with CPython 3.10 wheels. Only the 3.10 ceiling was declared, so a
  universal resolution satisfied every environment with that one version and
  never reached a current build. A matching `>=1.30` floor for 3.11+ forces the
  fork, and 3.10 stays installable.

## [0.6.1] - 2026-09-22

### Fixed

- The repository-hygiene scan rejected every `/home/<user>/projects/...` path,
  which failed CI on its own test suite: the WSL UNC tests have to name the
  POSIX path they resolve to. Placeholder user names are now allowed on POSIX
  exactly as they already were on Windows, and a real user name is still
  rejected.

## [0.6.0] - 2026-09-21

### Fixed

- An end card with a generated plate rendered without its own words. The plate
  is an absolutely positioned background image and the text is in-flow, so the
  image painted over it and the end card came out as a wordless gradient --
  silently defeating the rule that image tools draw backgrounds while every
  word is drawn locally. The text is now positioned above the plate, and a
  pixel test on a rendered frame asserts it.

### Added

- A second runtime mode, so a native Windows Codex agent can drive the Linux
  engine. `wsl-native` is unchanged and remains the default outcome for an
  agent already inside WSL; `windows-agent-wsl-runtime` is new; `linux-native`
  and `macos-native` are unchanged. `runtime_mode: auto` decides from the real
  platform of the agent process, whether `wsl.exe` runs, whether the chosen
  distribution reports WSL 2, and whether the engine is installed inside it --
  never from a terminal preference, which is configured separately and says
  nothing about where the agent runs. `runtime_mode` and `wsl_distribution` are
  new optional project-config fields, and `SOCIAL_VIDEO_RUNTIME_MODE` and
  `SOCIAL_VIDEO_WSL_DISTRIBUTION` override them.
- `scripts/windows/social-video-agent.ps1`, the one supported bridge. It passes
  arguments as an array rather than building a command string, uses no
  `Invoke-Expression` and no `sh -lc`, propagates stdout, stderr and the exit
  code, forwards Ctrl+C, and refuses to fall back to `ffmpeg.exe`, Windows
  Python or Windows Node -- a run that mixed Windows and Linux binaries would
  not be the run that was reviewed. Missing WSL, a broken WSL, no distribution,
  WSL 1 only, an ambiguous choice and a missing engine are five distinct
  diagnostics, and it installs nothing.
- Path normalisation across the boundary: quoted paths, and
  `\\wsl$\<distro>\...` / `\\wsl.localhost\<distro>\...` UNC paths, in
  addition to the drive letters, spaces, Polish characters, brackets, OneDrive
  folders and `/mnt/<drive>` paths already handled. Normalising twice is the
  same as normalising once, which is what stops `/mnt/c/mnt/c/...`. A UNC path
  for a different distribution is refused rather than silently resolved.
- Stage 0 writes `runtime.json`: the agent platform, the runtime mode, the
  distribution and its WSL version, the project path on each side, the Linux
  cache root, which engine binaries exist, the image policy and the Remotion
  licence declaration. Capabilities only the agent can see -- native ImageGen,
  Canva -- are written in a separate `session` block as `unknown_to_cli` and
  marked session-scoped, so a later run re-checks rather than trusting
  yesterday's tool list.
- `doctor` reports the agent side and the engine side separately in the hybrid
  mode, with one cause per line.
- `references/hybrid-runtime.md`, read only when the agent is on Windows. The
  blanket "no PowerShell/WSL bridge" rule became a precise one: no bridge in
  `wsl-native`, only the reviewed adapter in `windows-agent-wsl-runtime`, and
  never Windows and Linux binaries in the same render.
- `install_skills.py` also installs the skill folder into the Windows user's
  home when run from WSL, resolving that home from Windows rather than guessing
  a path under `/mnt/c/Users`. Only the skill crosses; no media dependency is
  duplicated on Windows.
- `remotion-license attest | status | refresh | revoke`: the Remotion license
  declaration can now be recorded once for a project instead of once per edit.
  It lives in `.social-video/remotion-license.json`, next to the branding config
  but deliberately not inside it, and records the declaration, the explicit
  acknowledgement, the moment, the component versions and the terms URL --
  nothing else. Eligibility is never derived from company size, revenue or any
  other signal, and there is no field in which such a signal could be supplied.
  `workflow init` and `render` take an explicit `--remotion-license` flag first,
  then the edit's own state when resuming, then the project declaration, and
  otherwise stop with the whole instruction. The CLI asks again after a
  revocation, a change of terms URL, a new release line, or a year;
  `refresh` re-confirms and never reinstates a revoked statement. Workflow state
  records `remotion_license_source`, and an older state without that field keeps
  its own declaration and is never asked again.
- Native image tools are supported without an API key of the user's own.
  Detection used to be credential-only, and reported "a ChatGPT plan does not
  include API image generation and Codex CLI has no image tool" when no key was
  set -- which is false on a host that hands its agent an ImageGen tool, and
  which turned a missing key into a claim that imagery was impossible. There
  are now four recognised sources: the host's native tool and a Canva MCP
  connection, both of which belong to the agent and cannot be called from
  Python; and the OpenAI and Gemini image APIs, which the CLI still calls
  itself. `image status` reports `cli_can_generate` plus
  `checked: local_api_integrations_only` and `native_imagegen: unknown_to_cli`,
  and never presents its own blindness as a verdict. New `image prompt` hands
  the agent the guarded no-text prompt to pass to its own tool verbatim;
  `image register` adopts the resulting file, copies it into the workspace,
  hashes it and records the tool that really drew it, leaving the model empty
  when the tool reports none; `image capabilities` records what the session can
  do, the source the agent chose and why, and refuses a record that contradicts
  itself. Consent is unchanged and now includes `--user-request` for one image
  the user asked for by name; `image_generation_policy: none` outranks every
  one-off, including the native tool. Nothing picks a source automatically,
  because availability is not a reason to use something.
- Measured voice cleanup, and `audio_cleanup_policy` to govern it. Until now
  the only thing done to the audio was loudness normalisation, so a recording
  with rumble, mains hum or an audible noise floor shipped with them. The
  render now measures the cut speech -- the per-window RMS distribution, so the
  noise floor is the 10th percentile and speech the 90th; energy below 60 Hz,
  where no voice lives; narrow bands at 50 and 60 Hz; 5-9 kHz; peak level --
  and applies only what crosses its own threshold, each with a ceiling: a
  two-pole high-pass at 80 Hz, a notch at the hum fundamental only, at most
  10 dB of `afftdn`, a de-esser at intensity 0.15, and at most 2:1
  compression. A well-recorded voice comes out untouched and the manifest
  records that every check ran below its threshold. This is not an "enhance
  voice" button: the same chain on every clip is how a good recording ends up
  sounding managed. Clipping is reported and never repaired, and hum harmonics
  are left alone because notching them thins the voice. Every render discloses
  what it changed and how to undo it (`--no-audio-cleanup`, or
  `audio_cleanup_policy: none`), the measurement and the ceilings land in the
  render manifest, and brand QA checks the repair against them. Policy defaults
  to `measured`, so an existing project gets it after re-validating; its source
  media is untouched either way.
- `config migrate`: a read-only report of every pre-0.4 value in a project
  config that still needs a human decision, with the old value, why it cannot
  be converted, and what to write instead.

### Fixed

- Remotion shortened long captions and made up an ellipsis. The compositor laid
  captions out with `-webkit-line-clamp` and `overflow: hidden`, which is a UI
  idiom for shortening a label, and the project config could not set
  `font_size_pct` or `max_chars_per_cue` even though `CaptionStyle` had both --
  so every project compiled to a 96-pixel caption at 1080x1920 and
  `nikomu, udowadniając na siłę` rendered as `nikomu, udowadniając na...`.
  Both keys are now part of `caption_style`, the reference 9:16 values
  (`font_size_pct: 3.6`, `max_words_per_cue: 4`, `max_chars_per_cue: 24`,
  `outline_or_shadow: none`, `corner_radius: 24`, `bottom_margin_pct: 22`) are
  the defaults for any key a config omits, and `config validate` refuses a
  geometry whose own text cannot be drawn at the configured resolution. Layout
  is measured in Python against the project font and shipped to the compositor
  as explicit lines, so there is no wrapping, clamping or ellipsis rule in the
  browser at all: a cue that does not fit is wrapped at word boundaries, then
  shrunk to at most 72% of the contracted size, then refused by name. Brand QA
  checks the geometry that was drawn -- lost text, an added ellipsis, a line
  wider than the box, a cue longer than the contract, a style that drifted from
  it -- rather than the geometry that was asked for.
- Migrating a pre-0.4 project config followed a recipe that could not work.
  The documented steps (add `schema_version`, rename two fields) left
  `punch_in_intensity: restrained`, `broll_density: low`, descriptive
  `music_policy`/`sfx_policy`/`default_fps_policy` and
  `caption_style.outline_or_shadow: subtle` to fail with a raw pydantic dump,
  and silently accepted fractional `safe_margins`: under the executable
  contract `0.15` is 0.15% of the frame, not 15%, so a config that validated
  rendered captions against the frame edge. Renames and YAML scalar shapes are
  still carried over silently; every value that encodes an editorial decision
  now raises `ConfigMigrationError` naming the field and the choices. Nothing
  is mapped for you, because a plausible default would overrule the editor.
- `context inspect` rejected configs that `config validate` compiles. The
  discovery model did not know `image_generation_policy` or `target_platforms`,
  so a valid 0.5 config failed discovery as "extra field", and it read only the
  pre-0.4 `logo`/`font` spellings when reporting logos and fonts. The two
  models are now locked to the same field set by a test, discovery keeps
  unknown keys as context instead of failing, and the executable contract stays
  the only gate that rejects a value.
- Context discovery pulled in files it had no business reading: anything under
  `docs/` scored as a candidate on location alone, so report archives whose
  name mentioned the brand, unrelated PDFs, and instruction files from
  `.codex/skills` became style sources. Dot directories other than
  `.social-video` and installed skill trees are skipped, candidates must have a
  readable or reusable extension, and a real brand signal is required rather
  than a directory name. Keyword inspection now looks for brand-specific
  phrases instead of words like "video" that appear in every status report, and
  a file named by the project config outranks the filename heuristic.

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

- Renders came out short of their own EDL on ffmpeg 7. Frame padding was
  expressed as a duration, and `0.033333333` is a hair under 1/30 of a second,
  so ffmpeg's floor turned "clone one frame" into "clone none". Any range whose
  source did not quite cover its allocated frames lost one, which put an
  ordinary multi-cut edit past the 45 ms QA tolerance on a current distribution.
  Padding is now counted in whole frames, and CI runs the render-timing suite on
  ffmpeg 7 as well so the next such regression is visible.
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
