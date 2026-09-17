# ADR-003: target-project context and persistent workflow stages

**Status:** accepted

**Date:** 2026-09-17

## Context

The plugin may be installed outside the repository where a video edit is
requested. Treating the skill installation as brand context produces incorrect
creative decisions. Model changes and new Codex conversations also cannot rely
on chat history to retain approved editorial state.

## Decision

The runtime distinguishes two roots:

- **skill root:** read-only plugin instructions and references;
- **target project root:** explicit user path, otherwise current directory's
  nearest Git root or current directory.

A bounded deterministic scanner ranks likely guidance and assets only within
the target root. It excludes dependencies, builds, caches, model files, render
workspaces, and symlinks that resolve outside the root. It reads a capped set of
small text/document excerpts, fingerprints relevant candidates, and persists
source paths, confidence, facts, conflicts, and unknowns under the edit
workspace's `context/` directory. An optional `.social-video/config.yaml` (or
root `social-video.yaml`) overrides heuristic evidence.

Each edit also owns `workflow-state.json`. It records Stage 1 planning, Stage 2
execution/preview, Stage 3 editorial review, Stage 4 finalization, and optional
Stage 5 delivery, along with required artifact paths and the next conceptual
model tier. Stage completion validates artifacts before advancing. Guided mode
stops at model boundaries; continuous mode uses the current model but retains
the same artifacts and checks.

The tier-to-model-name mapping exists only in
`src/social_video/workflow/model-routing.json`. State stores both the stable
tier and current display name. The application never claims to switch the host
model automatically.

## Consequences

- An edit resumes from files without prior chat history.
- Multiple edits cannot overwrite one global state file.
- Discovery stays local and does not package or upload customer brand assets.
- User instructions can override project defaults and remain visible in the
  edit plan.
- Changing model names requires one configuration edit rather than a schema
  migration.
- Static skill documentation is larger, so detailed material remains deferred
  in stage-specific references instead of the always-loaded `SKILL.md`.
