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

## Releasing

1. Bump the version everywhere it is pinned (`src/social_video/__init__.py`,
   `package.json`, the plugin manifests and the skill metadata) and move the
   changelog's Unreleased entries under the new version.
2. Run `./scripts/release-check.sh`.
3. Tag `vX.Y.Z` and push the tag. The release workflow builds the wheel, sdist
   and skill zip, and attaches them to a GitHub release with `SHA256SUMS`.

Publishing to PyPI uses trusted publishing, so no token is stored. It is off
until it is set up once:

1. On pypi.org, add a trusted publisher for the `social-video-agent` project:
   this repository, workflow `release.yml`, environment `pypi`.
2. In the repository settings, create the `pypi` environment and set the
   repository variable `PYPI_PUBLISH` to `true`.

The next tag then publishes the same wheel and sdist that the GitHub release
carries.

