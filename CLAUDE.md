# Claude Code guidance

Contributor rules live in `AGENTS.md`; follow them for all code changes.

## Commits

Match the existing history in this repository (`git log`):

- Conventional Commits subject: `feat: `, `fix: `, `chore: ` (add `docs: `, `refactor: `, `test: ` when they fit).
- One imperative subject line, lowercase after the type, no trailing period, aim for <= 60 characters.
- Subject only by default. Add a body only when the change needs explanation, separated by a blank line and wrapped at ~80 characters.
- No attribution, no `Co-Authored-By`, no `Generated with Claude Code`, no emoji, no tool footers in commit messages.
- Author identity comes from this repository's local git config; do not pass `--author`, do not hard-code a name or address here, and do not change the global config.
- Commit only when asked, and keep each commit focused.

Examples from this history:

```
feat: enforce executable branding and delivery
fix: preserve native Windows path semantics
chore: bump version to 0.2.0
```
