# Skill evaluation prompts

`skill-prompts.jsonl` is the small, reviewable scenario set for the canonical skill. It covers project-first behavior, bounded discovery, stage resume, one-model mode, budget guidance, and status handoff.

OpenAI's current `plugin-eval` is distributed in the `openai/plugins` repository and is intentionally not vendored here. With that CLI installed, run:

```bash
plugin-eval analyze skills/social-video-agent --format markdown
plugin-eval benchmark skills/social-video-agent --config .plugin-eval/benchmark.json
```

The repository's deterministic pytest coverage is the offline acceptance gate;
`plugin-eval` is optional because it is not bundled. Current official tooling
removed `--dry-run`: `benchmark` now runs real isolated `codex exec` sessions
and may consume account quota. Review `.plugin-eval/benchmark.json` and run it
only intentionally. If the executable is unavailable, record that explicitly
instead of claiming the benchmark ran.

The checked-in schema-v2 benchmark has six reviewed scenarios matching the
prompt set. Live Codex benchmarks are not part of CI. Run its deterministic
verifier without account use with:

```bash
uv run pytest -q tests/unit/test_project_context.py tests/unit/test_workflow.py
```
