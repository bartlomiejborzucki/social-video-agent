# Project context discovery

Use this before editorial planning. Its purpose is to locate and summarize
relevant local evidence, not recursively ingest a repository.

## Resolve the target

Precedence is: explicit user path, current working directory's nearest Git
root, then current directory. Stay inside that root. Applicable `AGENTS.md`
instructions are already enforced by Codex; record their presence without
trying to replace native instruction discovery.

Run:

```bash
social-video-agent context inspect PROJECT_ROOT --workspace WORKSPACE --json
```

Use `context refresh` when the user asks or when a relevant file changed. The
scanner fingerprints the ranked sources and otherwise reuses cached context.

## Progressive inspection

The deterministic scanner ranks likely sources by filename, location, type,
and bounded keyword inspection. It skips `.git`, dependencies, virtual
environments, builds, coverage, caches, models, renders, and frame directories.
It reads only a small top-ranked set with size/depth/count limits.

Inspect high-confidence sources first:

- `.social-video/config.yaml` or `social-video.yaml`;
- video/editing guidance and brandbooks;
- tone-of-voice and social guidance;
- logos, fonts, intro/outro, templates, caption assets;
- relevant design tokens or Remotion components;
- a very small sample of prior output only when it helps.

PDF/DOCX/PPTX candidates are high-value. Use host document inspection when
available or lightweight local extraction. Do not add OCR merely for discovery.
Treat website colors/fonts and previous renders as hints, never proof of video
rules.

## Precedence and confidence

Apply, in order:

1. current explicit user request;
2. explicit social-video project config;
3. applicable project instructions;
4. explicit video/editing guidance;
5. brandbook or tone-of-voice guidance;
6. social/video templates;
7. general design system;
8. previous output;
9. skill defaults.

Label claims `explicit`, `strongly_inferred`, or `weak_hint` and cite their
relative local paths. Record material conflicts instead of silently merging
them. Ask only when a conflict changes the output and higher-priority evidence
does not resolve it.

## Durable output

Store in the edit workspace, never the skill root:

```text
context/project-context.json
context/project-context.md
context/context-sources.json
```

The agent may enrich the deterministic summary with extracted facts, local
source citations, decisions, and short rationale. Do not store private
chain-of-thought. Never copy discovered assets into this public plugin.

Before Stage 1, briefly report what was found and which explicit guidance will
be used. If nothing relevant exists, say defaults will be used and continue.
