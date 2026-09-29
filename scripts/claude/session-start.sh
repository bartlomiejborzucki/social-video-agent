#!/usr/bin/env bash
# Claude Code SessionStart hook for the social-video-agent plugin.
#
# Prints a few lines about edits in progress in the opened project, which
# Claude Code adds to the session context. Quiet everywhere else, bounded by a
# timeout, and never fails the session.
set -u

dir="${CLAUDE_PROJECT_DIR:-$PWD}"

if ! command -v social-video-agent >/dev/null 2>&1; then
  if [[ -f "$dir/social-video.yaml" || -f "$dir/.social-video/config.yaml" ]]; then
    echo "social-video-agent: this project has a config, but the CLI is not on PATH;" \
      "install it and run \`social-video-agent doctor\`."
  fi
  exit 0
fi

if command -v timeout >/dev/null 2>&1; then
  timeout 10 social-video-agent -q workflow brief "$dir" 2>/dev/null || true
else
  social-video-agent -q workflow brief "$dir" 2>/dev/null || true
fi
exit 0
