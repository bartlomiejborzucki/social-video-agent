#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "ERROR: this bootstrap runs in Linux. On Windows, configure Codex Agent environment to Windows Subsystem for Linux and rerun it there." >&2
  exit 1
fi

if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
  distro="${WSL_DISTRO_NAME:-unknown WSL distribution}"
  echo "OK: WSL detected ($distro)."
else
  echo "WARNING: WSL was not detected. Continuing because ordinary Linux is supported."
fi

os_id="unknown"
os_like=""
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  os_id="${ID:-unknown}"
  os_like="${ID_LIKE:-}"
fi
echo "OK: Linux distribution: $os_id."

missing_packages=()
command -v python3 >/dev/null 2>&1 || missing_packages+=(python3)
command -v curl >/dev/null 2>&1 || missing_packages+=(curl ca-certificates)
command -v ffmpeg >/dev/null 2>&1 || missing_packages+=(ffmpeg)
command -v ffprobe >/dev/null 2>&1 || missing_packages+=(ffmpeg)
command -v fc-list >/dev/null 2>&1 || missing_packages+=(fontconfig)
fc-list 2>/dev/null | awk 'BEGIN { IGNORECASE=1 } /Noto Sans/ { found=1 } END { exit !found }' \
  || missing_packages+=(fonts-noto-core)

if ((${#missing_packages[@]})); then
  if command -v apt-get >/dev/null 2>&1 && [[ "$os_id $os_like" == *debian* || "$os_id" == "ubuntu" ]]; then
    mapfile -t missing_packages < <(printf '%s\n' "${missing_packages[@]}" | sort -u)
    echo "Installing required system packages: ${missing_packages[*]}"
    if [[ ! -t 0 ]] && ! sudo -n true 2>/dev/null; then
      echo "ERROR: system packages are missing and sudo needs an interactive password." >&2
      echo "Run this once in a WSL terminal, then rerun bootstrap:" >&2
      echo "  sudo apt-get update && sudo apt-get install -y ${missing_packages[*]}" >&2
      exit 1
    fi
    sudo apt-get update
    sudo apt-get install -y "${missing_packages[@]}"
  else
    echo "ERROR: install these prerequisites with the package manager for $os_id: ${missing_packages[*]}" >&2
    echo "Required commands: Python 3.10+, ffmpeg, ffprobe, fontconfig, and a font covering Polish characters (for example Noto Sans)." >&2
    exit 1
  fi
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv from the official Astral installer."
  installer="$(mktemp)"
  trap 'rm -f -- "$installer"' EXIT
  curl --proto '=https' --tlsv1.2 -fsSL https://astral.sh/uv/install.sh -o "$installer"
  sh "$installer"
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

cd "$PROJECT_ROOT"
uv sync --extra dev

mkdir -p "$HOME/.local/bin" "${XDG_CACHE_HOME:-$HOME/.cache}/social-video-agent"
ln -sfn "$PROJECT_ROOT/.venv/bin/social-video-agent" "$HOME/.local/bin/social-video-agent"
ln -sfn "$PROJECT_ROOT/.venv/bin/social-video" "$HOME/.local/bin/social-video"

echo "Running offline FFmpeg and Polish-caption smoke test."
uv run --no-sync pytest tests/integration/test_wsl_smoke.py -q

echo "Running project doctor."
"$PROJECT_ROOT/.venv/bin/social-video-agent" doctor

if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
  echo "WARNING: add this line to your shell profile, then open a new shell:"
  echo '  export PATH="$HOME/.local/bin:$PATH"'
fi

echo "READY: run social-video-agent doctor"
