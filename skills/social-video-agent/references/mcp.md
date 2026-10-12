# The workflow as MCP tools

When your session lists the `social-video-agent` MCP tools (`workflow_status`,
`workflow_init`, `render`, `motion_qa` and the rest), you may call them instead
of typing commands. Each tool runs the matching CLI command with `--json` in a
child process, so the stages, artifact gates, licence gate and QA are the same.
Every rule in this skill still applies.

- **Same order.** Start with `workflow_status`, follow `current_stage` and
  `missing_artifacts`, and write the editorial files yourself: the plan, the
  accepted candidates, `qa-editorial.json`, translations.
- **Results.** A tool returns `{"ok": true, "result": ...}` with the command's
  JSON, or `{"ok": false, "error": ...}` with its message. Read the error and
  act on it as you would the CLI's.
- **What is not a tool.** Declaring a Remotion licence, stating the right to
  download a recording, agreeing to a cloud image call and allowing brand files
  to be uploaded are the user's own acts. There are no tools for them. Ask, and
  let the user run the command, for example
  `social-video-agent remotion-license attest DECLARATION --accept-terms`.
- **No tools listed:** use the commands in the other references.

`social-video-agent mcp tools` lists every tool and the command it runs.
