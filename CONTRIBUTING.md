# Contributing

Use Linux, macOS, or WSL2. For Windows development, clone into the WSL filesystem rather than `/mnt/c`.

```bash
./scripts/wsl/bootstrap.sh   # Ubuntu/Debian WSL2
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy
uv run python scripts/validate_distribution.py
```

Keep changes focused, do not commit generated media or models, and preserve source-media immutability. Run `./scripts/release-check.sh` before release-oriented changes.
