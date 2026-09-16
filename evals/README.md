# Skill evaluation prompts

`skill-prompts.jsonl` is the small, reviewable scenario set for the canonical skill. It covers editing behavior, missing dependencies, Polish captions, and pasted Windows paths.

OpenAI's current `plugin-eval` is distributed in the `openai/plugins` repository and is intentionally not vendored here. With that CLI installed, run:

```bash
plugin-eval analyze skills/social-video-agent --format markdown
plugin-eval init-benchmark skills/social-video-agent
plugin-eval benchmark skills/social-video-agent --dry-run
```

Review the generated `.plugin-eval/benchmark.json` before any live benchmark. Live Codex benchmarks are not part of CI and may use network access and account quota.
