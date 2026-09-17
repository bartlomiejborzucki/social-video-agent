# Model routing and handoff

Conceptual tiers, not model names, are the durable contract:

| Tier | OpenAI | Claude alternative | Effort | Work |
|---|---|---|---|---|
| `editorial_strong` | Sol | Claude Opus 5 | high | context, hook, story, editorial review |
| `execution_balanced` | Terra | Claude Sonnet 5 | medium | EDL, captions, render, corrections |
| `mechanical_fast` | Luna | Claude Haiku 4.5 | low | delivery variants only |
| `escalation` | Astra | Claude Fable 5.1 | high | exceptional editorial or debugging impasse |

The executable mapping and authoritative current names live only in
`src/social_video/workflow/model-routing.json`. If names change, update that
file and its tests. The table above is user-facing documentation. Claude is an
alternative when available in the user's host; never imply that Codex can
switch provider or model automatically.

Claude names were verified on 2026-09-17 against Anthropic's
[current model overview](https://platform.claude.com/docs/en/models/overview).
Effort is a workflow recommendation only where the selected host/model exposes
that control.

Budgets:

- `balanced`: Sol → Terra → Sol → Terra; Luna optional for Stage 5.
- `economical`: Terra → Luna/Terra → Terra → Luna/Terra; use the CLI's current
  recommendation, which is the canonical mapping.
- `quality`: the balanced route, with Astra suggested only after a documented
  genuine impasse. Never choose Astra automatically.

At a guided boundary: save state, verify required artifacts, stop, show both
the OpenAI recommendation and Claude alternative, name the effort, explain in
one sentence, and give the exact next prompt in the user's language. This also
applies when entering Stages 4 and 5. Never say the model or provider was
switched automatically.

Example:

```text
Etap 1 zakończony.
Utworzono: edit-plan.json, context/project-context.json.
Zalecane modele: OpenAI Terra lub Claude Sonnet 5 (medium).
Dlaczego: decyzje redakcyjne są zapisane; kolejny etap to wykonanie.
Po zmianie wyślij: „Kontynuuj social-video-agent z Etapem 2.”
```

In `continuous` mode keep the checkpoints but do not stop for model changes.
Never let Stage 5 reopen the approved EDL or story.
