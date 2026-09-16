# Contributor guidance

- The primary Windows environment is Codex running inside WSL2. Keep the repository and high-I/O work in the Linux filesystem, normally under `~/projects`.
- Windows source and destination media may use `/mnt/c`, `/mnt/d`, or pasted drive-letter paths. Use the centralized path helper; never add ad-hoc string conversion.
- Use Linux `ffmpeg`, `ffprobe`, Python, Node, and Remotion. Never call `ffmpeg.exe` or add a PowerShell-to-WSL launcher.
- Source media is immutable. Write all intermediates and outputs to a workspace or explicit destination.
- Invoke subprocesses with argument arrays. Never use `shell=True` or `os.system` with media paths.
- Before handoff run `uv run pytest`, `uv run ruff check .`, `social-video-agent doctor`, and `./scripts/release-check.sh` when preparing a release.
- Validate the Codex manifest, marketplace, and skill with `uv run python scripts/validate_distribution.py`.
- Do not download ASR models, CUDA, GPU drivers, or large media in CI. Remotion and GPU support remain optional.
