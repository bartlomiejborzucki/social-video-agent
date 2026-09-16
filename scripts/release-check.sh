#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

uv sync --extra dev
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy
uv run --no-sync pytest -q
uv run --no-sync python scripts/validate_distribution.py
uv build
./scripts/build-skill.sh

if git grep -nEI '(sk-[A-Za-z0-9_-]{20,}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY)' -- ':!uv.lock'; then
  echo "ERROR: possible secret detected" >&2
  exit 1
fi

echo "Release checks passed."
