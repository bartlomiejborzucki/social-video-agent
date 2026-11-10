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
- **Every command has a tool or a stated reason.** A tool is named after its
  command (`hook_check`, `sources_add`, `captions_fix`, `motion_custom_check`)
  and takes the command's options under their own names, without the dashes.
- **What is not a tool.** Declaring a Remotion licence, stating the right to
  download a recording, agreeing to a cloud image call and allowing brand files
  to be uploaded are the user's own acts. There are no tools for them. Ask, and
  let the user run the command, for example
  `social-video-agent remotion-license attest DECLARATION --accept-terms`.
  The same holds for installing software (`doctor --install-ffmpeg`,
  `--install-remotion`), and `edit` is left out because it runs outside the
  stages.
- **A call that never answers** is reported after six hours
  (`SOCIAL_VIDEO_MCP_TIMEOUT`, in seconds) as `{"ok": false, "error": "timed
  out ..."}`; the server keeps running.
- **No tools listed:** use the commands in the other references.

`social-video-agent mcp tools` lists every tool and the command it runs.
