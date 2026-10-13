"""The workflow stages as MCP tools, behind the same gates as the CLI.

Every tool runs the matching CLI command, with `--json` where it has one, in
a child process: the artifact gates, the Remotion licence gate, brand QA and
the workflow state are exactly the CLI's, so an agent on any host that speaks
MCP -- Codex, Claude, others -- drives one implementation. A child process
also keeps every byte a command prints off the server's stdio channel.

Some commands are deliberately not tools. Declaring a Remotion licence,
stating the right to download a recording, agreeing to a cloud image call or
to uploading brand files are the user's own acts; an agent must not be able
to perform them by calling a tool.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Literal

Kind = Literal["string", "integer", "number", "boolean", "array"]

INSTRUCTIONS = (
    "Edits a recording into a Reel or Short through persisted stages. Start with "
    "workflow_status on the workspace, or workflow_init for a new edit, and follow "
    "its current_stage and missing_artifacts; never infer progress from the "
    "conversation. Editorial decisions -- the plan, which cuts and accents to "
    "accept, the Stage 3 review -- are yours to make and write as files. The "
    "Remotion licence declaration and every consent stay with the user: ask, and "
    "let them run `social-video-agent remotion-license attest` themselves."
)


@dataclass(frozen=True)
class Param:
    name: str
    kind: Kind = "string"
    #: The CLI option, or None for a positional argument.
    flag: str | None = None
    required: bool = False
    description: str = ""
    #: For a boolean whose CLI default is on: the flag that turns it off.
    negative: str | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    command: tuple[str, ...]
    description: str
    params: tuple[Param, ...] = ()
    json_flag: bool = True

    def schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        for p in self.params:
            spec: dict[str, Any] = {"type": p.kind, "description": p.description}
            if p.kind == "array":
                spec["items"] = {"type": "string"}
            properties[p.name] = spec
        return {
            "type": "object",
            "properties": properties,
            "required": [p.name for p in self.params if p.required],
            "additionalProperties": False,
        }


def _ws(required: bool = True, flag: str | None = "--workspace") -> Param:
    return Param("workspace", flag=flag, required=required, description="Edit workspace path.")


SOURCE = Param("source", required=True, description="Source recording; it is never modified.")
LANGUAGE = Param("language", flag="--language", description="Language code, e.g. pl or en.")
PROJECT = Param("project_root", flag="--project-root", description="Target project root.")
IDS = Param("ids", kind="array", description="Candidate ids to accept.")
KINDS = Param("kind", kind="array", flag="--kind", description="Accept every candidate of a kind.")
CONFIDENCE = Param("confidence", flag="--confidence", description="high or medium.")

TOOLS: tuple[Tool, ...] = (
    Tool("workflow_status", ("workflow", "status"),
         "Where an edit, or a batch of edits, stands: stage, missing artifacts, next prompt.",
         (_ws(flag=None), LANGUAGE)),
    Tool("workflow_init", ("workflow", "init"),
         "Start an edit: Stage 0 licence gate, project discovery, ingest. Never renders.",
         (SOURCE, _ws(required=False), PROJECT,
          Param("renderer", flag="--renderer", description="remotion (default) or ffmpeg."),
          Param("remotion_license", flag="--remotion-license",
                description="Only a declaration the user made in so many words."),
          Param("model_budget", flag="--model-budget"),
          Param("workflow_mode", flag="--workflow-mode"),
          LANGUAGE)),
    Tool("workflow_batch", ("workflow", "batch"),
         "Start one edit per recording in a folder, under a parent workspace.",
         (Param("directory", required=True, description="Folder of recordings."),
          _ws(), PROJECT, Param("renderer", flag="--renderer"),
          Param("remotion_license", flag="--remotion-license",
                description="Only a declaration the user made in so many words."),
          LANGUAGE)),
    Tool("workflow_complete", ("workflow", "complete"),
         "Validate a stage's artifacts and advance to the next stage.",
         (Param("stage", kind="integer", required=True, description="1 to 5."), _ws(), LANGUAGE)),
    Tool("remotion_license_status", ("remotion-license", "status"),
         "Whether the project holds a usable Remotion licence declaration.", (PROJECT,)),
    Tool("config_validate", ("config", "validate"),
         "Compile the project config into brand-contract.json, or say what is wrong.",
         (Param("project_root", description="Target project root."), _ws(required=False))),
    Tool("context_inspect", ("context", "inspect"),
         "Discover the target project's brand and editing context.",
         (Param("project_root", description="Target project root."), _ws(required=False))),
    Tool("transcribe", ("transcribe",), "Transcribe the source locally, with word timings.",
         (SOURCE, _ws(required=False), Param("backend", flag="--backend"),
          Param("model", flag="--model"), LANGUAGE,
          Param("diarize", kind="boolean", flag="--diarize", description="Label speakers."))),
    Tool("pack", ("pack",), "Write takes-packed.md, the compact transcript to reason over.",
         (_ws(flag=None),), json_flag=False),
    Tool("plan", ("plan",), "Write a mechanical first-pass edit plan to revise.",
         (SOURCE, _ws(required=False), Param("profile", flag="--profile"),
          Param("goal", flag="--goal"), LANGUAGE)),
    Tool("compile", ("compile",), "Compile edit-plan.json into a word-aligned edl.json.",
         (SOURCE, _ws(required=False), Param("profile", flag="--profile"),
          Param("reframe", flag="--reframe"), LANGUAGE,
          Param("force", kind="boolean", flag="--force", description="Replace an existing EDL."))),
    Tool("cuts_find", ("cuts", "find"), "List hesitations, restarts and long pauses to cut.",
         (SOURCE, _ws(required=False), LANGUAGE)),
    Tool("cuts_accept", ("cuts", "accept"), "Accept cut candidates by id or kind.",
         (IDS, _ws(), KINDS, CONFIDENCE)),
    Tool("motion_suggest", ("motion", "suggest"), "List accents found in what is said.",
         (SOURCE, _ws(), Param("energy", flag="--energy"), LANGUAGE)),
    Tool("motion_accept", ("motion", "accept"), "Accept accents into motion-plan.json.",
         (IDS, _ws(), KINDS, CONFIDENCE)),
    Tool("broll_suggest", ("broll", "suggest"), "Match the user's b-roll library to the speech.",
         (SOURCE, Param("library", flag="--library", required=True), _ws())),
    Tool("broll_accept", ("broll", "accept"), "Cut accepted b-roll in as overlays.",
         (IDS, _ws()), json_flag=False),
    Tool("render", ("render",), "Render the workspace's EDL.",
         (_ws(flag=None), Param("quality", flag="--quality", description="preview or final."),
          Param("renderer", flag="--renderer"))),
    Tool("qa", ("qa",), "Technical, platform and brand QA of a render.",
         (_ws(flag=None), Param("platform", kind="array", flag="--platform"))),
    Tool("motion_qa", ("motion", "qa"), "Measure every graphic; required at Stage 3 on Remotion.",
         (_ws(), Param("faces", kind="boolean", negative="--no-faces",
                       description="Measure faces under graphics (default true)."))),
    Tool("motion_sheet", ("motion", "sheet"), "One labelled frame per piece of motion.",
         (_ws(), Param("video", flag="--video")), json_flag=False),
    Tool("motion_film_spec", ("motion", "film", "spec"),
         "Write a Claude Motion film spec for full-frame graphics.",
         (_ws(), Param("scene", kind="array", flag="--scene"), Param("film_id", flag="--film-id"),
          Param("title", flag="--title"),
          Param("claude_motion", flag="--claude-motion",
                description="available or unavailable, from your own tool list."),
          Param("force", kind="boolean", flag="--force"))),
    Tool("motion_film_import", ("motion", "film", "import"),
         "Import the user's Motion export as one segment per scene.",
         (Param("export", required=True, description="The MP4 the user exported."), _ws(),
          Param("film_id", flag="--film-id", required=True),
          Param("font_used", flag="--font-used", required=True),
          Param("scene", kind="array", flag="--scene"))),
    Tool("motion_film_status", ("motion", "film", "status"),
         "Films specified, segments imported, scenes waiting for an export.", (_ws(),)),
    Tool("captions_translate", ("captions", "translate"),
         "Write the cues for you to translate.",
         (_ws(), Param("to", flag="--to", required=True),
          Param("force", kind="boolean", flag="--force")),
         json_flag=False),
    Tool("captions_apply", ("captions", "apply"), "Check a translation and write its tracks.",
         (_ws(), Param("to", flag="--to", required=True), Param("file", flag="--file"),
          Param("max_chars", kind="integer", flag="--max-chars"))),
    Tool("brief_import", ("brief", "import"),
         "Make a montage brief this edit's override: first caption, labels, cover text.",
         (Param("file", required=True, description="Brief text or the package JSON."), _ws(),
          Param("entry", kind="integer", flag="--entry"), Param("match", flag="--match"),
          Param("labels", kind="boolean", flag="--labels",
                description="Add the brief's on-screen texts to motion-plan.json."))),
    Tool("opening_qa", ("opening-qa",),
         "Check the opening: scene at frame 0, caption at 0.0 s, no card, no silence.",
         (_ws(flag=None), Param("video", flag="--video"),
          Param("first_frame_note", flag="--first-frame-note",
                description="One sentence on frame 0, after looking at first-frame.png."))),
    Tool("apply_editorial_qa", ("apply-editorial-qa",),
         "Apply only the validated fixes in qa-editorial.json.", (_ws(flag=None),)),
    Tool("deliver", ("deliver",), "Stage 5: immutable variants and a verified manifest.",
         (_ws(flag=None), Param("output", flag="--output"),
          Param("with_captions", kind="boolean", flag="--with-captions"),
          Param("no_captions", kind="boolean", flag="--no-captions"),
          Param("srt", kind="boolean", flag="--srt"), Param("vtt", kind="boolean", flag="--vtt"),
          Param("poster", kind="boolean", flag="--poster"),
          Param("cover", kind="boolean", flag="--cover"),
          Param("publish", kind="boolean", flag="--publish"),
          Param("platform", kind="array", flag="--platform"),
          Param("resolution", kind="array", flag="--resolution"),
          Param("language", kind="array", flag="--language"),
          Param("first_frame_note", flag="--first-frame-note"))),
    Tool("export_timeline", ("export",), "Write the cut as an NLE timeline.",
         (_ws(flag=None), Param("format", flag="--format"), Param("output", flag="--output"))),
    Tool("platforms", ("platforms",), "Publishing destinations and their reserved zones."),
    Tool("doctor", ("doctor",), "Check this machine can produce a correct video."),
)  # fmt: skip

BY_NAME = {tool.name: tool for tool in TOOLS}


class ToolInputError(ValueError):
    """The arguments do not fit the tool."""


def argv_for(tool: Tool, arguments: dict[str, Any]) -> list[str]:
    """The CLI arguments for one call, checked against the tool's parameters."""
    known = {p.name for p in tool.params}
    unknown = sorted(set(arguments) - known)
    if unknown:
        raise ToolInputError(f"{tool.name} takes no {', '.join(unknown)}")
    missing = [p.name for p in tool.params if p.required and arguments.get(p.name) in (None, "")]
    if missing:
        raise ToolInputError(f"{tool.name} needs {', '.join(missing)}")
    positional: list[str] = []
    options: list[str] = []
    for p in tool.params:
        value = arguments.get(p.name)
        if value is None:
            continue
        if p.kind == "boolean":
            if not isinstance(value, bool):
                raise ToolInputError(f"{p.name} is true or false")
            if value and p.flag:
                options.append(p.flag)
            if not value and p.negative:
                options.append(p.negative)
            continue
        values = value if p.kind == "array" else [value]
        if not isinstance(values, list):
            raise ToolInputError(f"{p.name} is a list")
        for item in values:
            text = str(item)
            if p.flag is None:
                positional.append(text)
            else:
                options += [p.flag, text]
    return [*tool.command, *positional, *options, *(["--json"] if tool.json_flag else [])]


def run_cli(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """One CLI command in a child process, with plain, wide output."""
    env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "400"}
    return subprocess.run(
        [sys.executable, "-m", "social_video", *argv],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def call_tool(name: str, arguments: dict[str, Any] | None = None, *, runner=run_cli) -> dict:
    """Run one tool and say what happened, as data an agent can act on."""
    tool = BY_NAME.get(name)
    if tool is None:
        return {"ok": False, "error": f"no tool {name!r}; known: {', '.join(sorted(BY_NAME))}"}
    try:
        argv = argv_for(tool, arguments or {})
    except ToolInputError as exc:
        return {"ok": False, "error": str(exc)}
    proc = runner(argv)
    result: dict[str, Any] = {"ok": proc.returncode == 0, "command": argv}
    output = proc.stdout.strip()
    if tool.json_flag and output:
        try:
            result["result"] = json.loads(output)
        except json.JSONDecodeError:
            result["output"] = output
    elif output:
        result["output"] = output
    if proc.returncode != 0:
        result["error"] = (proc.stderr.strip() or output or f"exit code {proc.returncode}")[-4000:]
    return result


def build_server():
    """The MCP server: one tool per entry in `TOOLS`."""
    import anyio
    import mcp.types as types
    from mcp.server.lowlevel import Server

    from social_video import __version__

    async def list_tools(_ctx, _params) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(name=t.name, description=t.description, input_schema=t.schema())
                for t in TOOLS
            ]
        )

    async def run_tool(_ctx, params) -> types.CallToolResult:
        result = await anyio.to_thread.run_sync(
            lambda: call_tool(params.name, dict(params.arguments or {}))
        )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            is_error=not result["ok"],
        )

    return Server(
        "social-video-agent",
        version=__version__,
        instructions=INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=run_tool,
    )


def serve() -> None:
    """Serve the tools over stdio until the client disconnects."""
    import anyio
    from mcp.server.stdio import stdio_server

    server = build_server()

    async def main() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(main)
