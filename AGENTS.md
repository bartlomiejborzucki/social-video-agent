# Contributor guidance

- The primary Windows environment is Codex running inside WSL2. Keep the repository and high-I/O work in the Linux filesystem, normally under `~/projects`.
- Windows source and destination media may use `/mnt/c`, `/mnt/d`, or pasted drive-letter paths. Use the centralized path helper; never add ad-hoc string conversion.
- Use Linux `ffmpeg`, `ffprobe`, Python, Node, and Remotion. Never call `ffmpeg.exe` or add a PowerShell-to-WSL launcher.
- Source media is immutable. Write all intermediates and outputs to a workspace or explicit destination.
- Keep the skill root separate from the target project root. Project-context discovery is bounded to the target root, runs before editorial planning, and persists under that edit's `context/` directory.
- Resume staged edits from `workflow-state.json`; do not rely on chat history. Guided stages are editorial plan, execution/preview, supervising review, finalization, and optional mechanical delivery.
- Model code uses conceptual tiers. The only tier-to-name mapping is `src/social_video/workflow/model-routing.json`; do not duplicate it in Python or contributor docs.
- Keep `SKILL.md` concise and route detailed behavior to `references/` through progressive disclosure.
- Invoke subprocesses with argument arrays. Never use `shell=True` or `os.system` with media paths.
- Before handoff run `uv run pytest`, `uv run ruff check .`, `social-video-agent doctor`, and `./scripts/release-check.sh` when preparing a release.
- Validate the Codex manifest, marketplace, and skill with `uv run python scripts/validate_distribution.py`.
- Run context/workflow regressions when changing discovery, stage schemas, or handoffs: `uv run pytest tests/unit/test_project_context.py tests/unit/test_workflow.py`.
- Do not download ASR models, CUDA, GPU drivers, or large media in CI. Remotion and GPU support remain optional.
