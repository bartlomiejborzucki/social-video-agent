# Contributor guidance

- The primary Windows environment is Codex running inside WSL2. Keep the repository and high-I/O work in the Linux filesystem, normally under `~/projects`.
- Windows source and destination media may use `/mnt/c`, `/mnt/d`, or pasted drive-letter paths. Use the centralized path helper; never add ad-hoc string conversion.
- Use Linux `ffmpeg`, `ffprobe`, Python, Node, and Remotion. Remotion is the default compositor for new workflows; Stage 0 must record a license declaration before discovery or media work. Never call `ffmpeg.exe` or add a PowerShell-to-WSL launcher.
- Source media is immutable. Write all intermediates and outputs to a workspace or explicit destination.
- Keep the skill root separate from the target project root. Project-context discovery is bounded to the target root, runs before editorial planning, and persists under that edit's `context/` directory.
- Resume staged edits from `workflow-state.json`; do not rely on chat history. Guided stages are editorial plan, execution/preview, supervising review, finalization, and optional mechanical delivery.
- Model code uses conceptual tiers. The only tier-to-name mapping is `src/social_video/workflow/model-routing.json`; do not duplicate it in Python or contributor docs.
- Keep `SKILL.md` concise and route detailed behavior to `references/` through progressive disclosure.
- Invoke subprocesses with argument arrays. Never use `shell=True` or `os.system` with media paths.
- Before handoff run `uv run pytest`, `uv run ruff check .`, `social-video-agent doctor`, and `./scripts/release-check.sh` when preparing a release.
- Validate the Codex manifest, marketplace, and skill with `uv run python scripts/validate_distribution.py`.
- Run context/workflow regressions when changing discovery, stage schemas, or handoffs: `uv run pytest tests/unit/test_project_context.py tests/unit/test_workflow.py`.
- Stage 2 must write a project-aware `motion-plan.json`; keep motion restrained and reviewable rather than adding effects to fill space. FFmpeg owns cuts/audio/timing, Remotion owns the approved visual layer, and FFmpeg/ffprobe own final QA.
- Do not download ASR models, CUDA, GPU drivers, or large media in CI. The dedicated Remotion job may install locked npm packages and Chrome Headless Shell; GPU support remains optional.
