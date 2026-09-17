# Model routing and handoff

Conceptual tiers, not model names, are the durable contract:

| Tier | Current preference | Work |
|---|---|---|
| `editorial_strong` | Sol, high | context, hook, story, editorial review |
| `execution_balanced` | Terra, medium | EDL, captions, render, corrections |
| `mechanical_fast` | Luna, low | delivery variants only |
| `escalation` | Astra, high | exceptional editorial or debugging impasse |

The executable mapping lives only in
`src/social_video/workflow/model-routing.json`. If names change, update that
file and its tests; do not scatter replacements through the skill.

Budgets:

- `balanced`: Sol → Terra → Sol → Terra; Luna optional for Stage 5.
- `economical`: Terra → Luna/Terra → Terra → Luna/Terra; use the CLI's current
  recommendation, which is the canonical mapping.
- `quality`: the balanced route, with Astra suggested only after a documented
  genuine impasse. Never choose Astra automatically.

At a guided boundary: save state, verify required artifacts, stop, name the
recommended model and effort, explain in one sentence, and give the exact next
prompt in the user's language. Never say the model was switched automatically.

Example:

```text
Etap 1 zakończony.
Utworzono: edit-plan.json, context/project-context.json.
Następny model: Terra (medium).
Dlaczego: decyzje redakcyjne są zapisane; kolejny etap to wykonanie.
Po zmianie wyślij: „Kontynuuj social-video-agent z Etapem 2.”
```

In `continuous` mode keep the checkpoints but do not stop for model changes.
Never let Stage 5 reopen the approved EDL or story.
