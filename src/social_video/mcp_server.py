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
MODEL = Param("model", flag="--model", description="Transcription model size.")
BACKEND = Param("backend", flag="--backend", description="Transcription backend.")
AUDIO_TRACK = Param("audio_track", kind="integer", flag="--audio-track",
                    description="Zero-based audio track.")  # fmt: skip
VIDEO = Param("video", flag="--video", description="Render to look at; default final or preview.")
LICENSE = Param("remotion_license", flag="--remotion-license",
                description="Only a declaration the user made in so many words.")  # fmt: skip

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
          Param("quick", kind="boolean", flag="--quick",
                description="Continuous workflow on the current model."),
          Param("refresh_context", kind="boolean", flag="--refresh-context"),
          Param("id", flag="--id", description="Id plans use for the source; default its stem."),
          LANGUAGE)),
    Tool("workflow_batch", ("workflow", "batch"),
         "Start one edit per recording in a folder, under a parent workspace.",
         (Param("directory", required=True, description="Folder of recordings."),
          _ws(), PROJECT, Param("renderer", flag="--renderer"), LICENSE,
          Param("model_budget", flag="--model-budget"),
          Param("workflow_mode", flag="--workflow-mode"),
          LANGUAGE)),
    Tool("workflow_resume", ("workflow", "resume"),
         "Resume from files only: the same answer as workflow_status.",
         (_ws(flag=None), LANGUAGE)),
    Tool("workflow_renderer", ("workflow", "renderer"),
         "Switch the workflow's renderer; Remotion goes through the licence gate.",
         (Param("renderer", required=True, description="remotion or ffmpeg."),
          _ws(required=False), LICENSE, LANGUAGE)),
    Tool("workflow_brief", ("workflow", "brief"),
         "A few lines on edits in progress under a directory, for a session start.",
         (Param("root", description="Directory the session opened."),)),
    Tool("workflow_complete", ("workflow", "complete"),
         "Validate a stage's artifacts and advance to the next stage.",
         (Param("stage", kind="integer", required=True, description="1 to 5."), _ws(), LANGUAGE)),
    Tool("remotion_license_status", ("remotion-license", "status"),
         "Whether the project holds a usable Remotion licence declaration.", (PROJECT,)),
    Tool("config_init", ("config", "init"),
         "Write .social-video/config.yaml with every style decision spelled out.",
         (Param("project_root", description="Target project root."),
          Param("motion_energy", flag="--motion-energy", description="calm, lively or bold."),
          Param("style_pack", flag="--style-pack",
                description="editorial, bold-social or tech-minimal."),
          Param("label_style", flag="--label-style", description="chip or scene_frame."),
          Param("karaoke", kind="boolean", flag="--karaoke", negative="--no-karaoke",
                description="Colour the word being spoken."),
          Param("animation", flag="--animation", description="none, pop or box."),
          Param("emphasis_words", flag="--emphasis-words",
                description="Brand words, comma separated."),
          Param("force", kind="boolean", flag="--force", description="Replace a config.")),
         json_flag=False),
    Tool("config_validate", ("config", "validate"),
         "Compile the project config into brand-contract.json, or say what is wrong.",
         (Param("project_root", description="Target project root."), _ws(required=False))),
    Tool("config_migrate", ("config", "migrate"),
         "Report every old config value that still needs a human decision.",
         (Param("project_root", description="Target project root."),)),
    Tool("context_inspect", ("context", "inspect"),
         "Discover the target project's brand and editing context.",
         (Param("project_root", description="Target project root."), _ws(required=False))),
    Tool("context_refresh", ("context", "refresh"),
         "Scan the project again and replace the cached context.",
         (Param("project_root", description="Target project root."), _ws(required=False))),
    Tool("inspect", ("inspect",), "Probe a source file and report what it actually is.",
         (SOURCE,)),
    Tool("sources_add", ("sources", "add"),
         "Add recordings to a workspace's source manifest; they stay immutable.",
         (Param("files", kind="array", required=True, description="Recordings to add."),
          _ws(), Param("id", flag="--id", description="Id for a single file; default its stem."))),
    Tool("sources_list", ("sources", "list"),
         "The workspace's recordings and whether each has a transcript.", (_ws(),)),
    Tool("transcribe", ("transcribe",), "Transcribe the source locally, with word timings.",
         (SOURCE, _ws(required=False), BACKEND, MODEL, LANGUAGE, AUDIO_TRACK,
          Param("diarize", kind="boolean", flag="--diarize", description="Label speakers."),
          Param("speakers", kind="integer", flag="--speakers",
                description="Known number of speakers."),
          Param("no_vad", kind="boolean", flag="--no-vad",
                description="Disable voice-activity filtering."),
          Param("refine", kind="array", flag="--refine",
                description="Re-transcribe only START-END seconds and splice the words in."),
          Param("force", kind="boolean", flag="--force",
                description="Re-transcribe even if cached."))),
    Tool("pack", ("pack",), "Write takes-packed.md, the compact transcript to reason over.",
         (_ws(flag=None),
          Param("silence", kind="number", flag="--silence",
                description="Gap that starts a new phrase."),
          Param("max_words", kind="integer", flag="--max-words",
                description="Cap on words per phrase.")),
         json_flag=False),
    Tool("plan", ("plan",), "Write a mechanical first-pass edit plan to revise.",
         (SOURCE, _ws(required=False), Param("profile", flag="--profile"),
          Param("goal", flag="--goal"), LANGUAGE, MODEL, BACKEND, AUDIO_TRACK,
          Param("force", kind="boolean", flag="--force",
                description="Re-transcribe even if cached."))),
    Tool("brief_story", ("brief", "story"),
         "Write a text story's edit plan: a sentence per shot, no speech, nothing transcribed.",
         (Param("file", required=True, description="The story, one line per shot."), _ws(),
          Param("cut_every", kind="number", flag="--cut-every",
                description="Seconds each shot is held, 1.0-1.5, unless its line says."),
          Param("force", kind="boolean", flag="--force",
                description="Replace an existing edit-plan.json."))),
    Tool("compile", ("compile",), "Compile edit-plan.json into a word-aligned edl.json.",
         (SOURCE, _ws(required=False), Param("profile", flag="--profile"),
          Param("reframe", flag="--reframe"), LANGUAGE, MODEL, BACKEND, AUDIO_TRACK,
          Param("captions", kind="boolean", flag="--captions", negative="--no-captions",
                description="Build the caption track; default when there is a brand contract."),
          Param("word_edges", kind="boolean", flag="--word-edges",
                description="Cut on the recognised word times instead of the heard edges."),
          Param("force", kind="boolean", flag="--force", description="Replace an existing EDL."))),
    Tool("cuts_find", ("cuts", "find"), "List hesitations, restarts and long pauses to cut.",
         (SOURCE, _ws(required=False), Param("profile", flag="--profile"), LANGUAGE, MODEL,
          BACKEND, AUDIO_TRACK)),
    Tool("cuts_accept", ("cuts", "accept"), "Accept cut candidates by id or kind.",
         (IDS, _ws(), KINDS, CONFIDENCE)),
    Tool("motion_suggest", ("motion", "suggest"), "List accents found in what is said.",
         (SOURCE, _ws(), Param("energy", flag="--energy"), LANGUAGE, MODEL,
          Param("hook_punch", kind="boolean", flag="--hook-punch",
                description="Also propose a push-in on the first key word at 1.0-1.5 s."),
          Param("sensitive", kind="boolean", flag="--sensitive",
                description="Death, illness or grief: no strike, bubble, process or icon."))),
    Tool("motion_accept", ("motion", "accept"), "Accept accents into motion-plan.json.",
         (IDS, _ws(), KINDS, CONFIDENCE)),
    Tool("broll_suggest", ("broll", "suggest"), "Match the user's b-roll library to the speech.",
         (SOURCE, Param("library", flag="--library", required=True), _ws(), MODEL)),
    Tool("broll_accept", ("broll", "accept"), "Cut accepted b-roll in as overlays.",
         (IDS, _ws()), json_flag=False),
    Tool("motion_sfx", ("motion", "sfx"),
         "Put a whoosh under each transition and a pop under each graphic.",
         (Param("library_dir", description="The user's effects folder; omit for the CC0 set."),
          _ws(), Param("gain_db", kind="number", flag="--gain-db"))),
    Tool("motion_custom_init", ("motion", "custom", "init"),
         "Write a component template to motion/custom/ID.tsx, with the props it receives.",
         (Param("component", required=True, description="The component's id."), _ws(),
          Param("force", kind="boolean", flag="--force")),
         json_flag=False),
    Tool("motion_custom_check", ("motion", "custom", "check"),
         "Check a component (imports, forbidden calls, tsc) and render its range to qa/.",
         (Param("component", required=True, description="The component's id."), _ws(), VIDEO,
          Param("render", kind="boolean", negative="--no-render",
                description="Render its range (default true)."))),
    Tool("render", ("render",), "Render the workspace's EDL.",
         (_ws(flag=None), Param("quality", flag="--quality", description="preview or final."),
          Param("renderer", flag="--renderer"),
          Param("output", flag="--output", description="Exact destination for the render."),
          Param("audio_cleanup", kind="boolean", negative="--no-audio-cleanup",
                description="Apply the measured voice cleanup (default true)."))),
    Tool("qa", ("qa",), "Technical, platform and brand QA of a render.",
         (_ws(flag=None), Param("platform", kind="array", flag="--platform"),
          Param("output", flag="--output", description="File to inspect."))),
    Tool("hook_check", ("hook", "check"),
         "Advisory read of the opening: the first caption and the first second.",
         (_ws(flag=None), VIDEO)),
    Tool("motion_qa", ("motion", "qa"), "Measure every graphic; required at Stage 3 on Remotion.",
         (_ws(), VIDEO,
          Param("faces", kind="boolean", negative="--no-faces",
                description="Measure faces under graphics (default true)."))),
    Tool("motion_sheet", ("motion", "sheet"), "One labelled frame per piece of motion.",
         (_ws(), Param("video", flag="--video")), json_flag=False),
    Tool("motion_variants", ("motion", "variants"),
         "Opening variants along one axis (text or first_shot), each with its hypothesis.",
         (_ws(), Param("axis", flag="--axis", description="text or first_shot."),
          Param("text", kind="array", flag="--text", description="Text axis: opening lines."),
          Param("from_brief", kind="boolean", flag="--from-brief"),
          Param("first_shot", kind="array", flag="--first-shot",
                description="First-shot axis: SOURCE:START-END per variant."),
          Param("pickup", kind="array", flag="--pickup",
                description="A variant to film first; recorded, not rendered."),
          Param("hypothesis", kind="array", flag="--hypothesis",
                description="What each variant tests, in order."),
          Param("only", kind="array", flag="--only", description="Re-render recorded variants."),
          Param("seconds", kind="number", flag="--seconds", description="Preview length."),
          Param("full", kind="boolean", flag="--full", description="Render full length."),
          Param("quality", flag="--quality",
                description="Default: final with full, preview otherwise."))),
    Tool("style_analyze", ("style", "analyze"),
         "Measure a reference video's rhythm; with editorial, pull stills for a read.",
         (Param("reference", required=True, description="A reference the user supplied."), _ws(),
          Param("transcribe", kind="boolean", flag="--transcribe"),
          Param("editorial", kind="boolean", flag="--editorial",
                description="Stills and timed transcript under context/reference/."),
          Param("frames", kind="integer", flag="--frames"), LANGUAGE, MODEL)),
    Tool("style_check_analysis", ("style", "check-analysis"),
         "Check your read of the reference: anchored observations, cited hypotheses.",
         (Param("analysis_file", description="Default: context/reference-analysis.json."),
          _ws())),
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
          Param("scene", kind="array", flag="--scene"),
          Param("tolerance_frames", kind="number", flag="--tolerance-frames",
                description="How far the export's length may differ, in frames."))),
    Tool("motion_film_remove", ("motion", "film", "remove"),
         "Take a segment out of the edit and put back the graphic it replaced.",
         (Param("scene_id", required=True, description="Scene id, e.g. hook-card-1."), _ws(),
          Param("film_id", flag="--film-id", required=True)),
         json_flag=False),
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
    Tool("captions_fix", ("captions", "fix"),
         "Correct the words of one caption; its timing stays as recognised.",
         (_ws(),
          Param("at", kind="number", flag="--at", required=True,
                description="Output time the caption is on screen, seconds."),
          Param("from", flag="--from", required=True,
                description="The word(s) to replace, as captioned."),
          Param("to", flag="--to", required=True,
                description="What the caption should say instead."))),
    Tool("brief_import", ("brief", "import"),
         "Make a montage brief this edit's override: first caption, labels, cover text.",
         (Param("file", required=True, description="Brief text or the package JSON."), _ws(),
          Param("entry", kind="integer", flag="--entry"), Param("match", flag="--match"),
          Param("labels", kind="boolean", flag="--labels",
                description="Add the brief's on-screen texts to motion-plan.json."))),
    Tool("brief_show", ("brief", "show"), "Print the brief this edit was given.", (_ws(),),
         json_flag=False),
    Tool("opening_qa", ("opening-qa",),
         "Check the opening: scene at frame 0, caption at 0.0 s, no card, no silence.",
         (_ws(flag=None), VIDEO,
          Param("first_frame_note", flag="--first-frame-note",
                description="One sentence on frame 0, after looking at first-frame.png."))),
    Tool("reel_check", ("reel-check",),
         "Advisory short-form checks: hook speed, length, dead air, holds, captions, asks.",
         (_ws(flag=None), VIDEO, Param("platform", kind="array", flag="--platform"))),
    Tool("cover", ("cover",),
         "Compose the cover still: brand typography over a real frame or a plate.",
         (_ws(flag=None), Param("title", flag="--title"), Param("subtitle", flag="--subtitle"),
          Param("from_brief", kind="boolean", flag="--from-brief",
                description="Take the title and subtitle from the brief."),
          Param("plate", flag="--plate", description="A background plate already recorded."),
          Param("frame_at", kind="number", flag="--frame-at",
                description="Take the background from the finished video at this second."),
          Param("layout", kind="array", flag="--layout",
                description="bottom, top, boxed or number; several draw side by side."),
          Param("figure", flag="--figure", description="The figure the number layout draws."),
          Param("output", flag="--output"))),
    Tool("shorts_list", ("shorts", "list"),
         "The clip candidates you wrote in candidates.json, best first.", (_ws(flag=None),)),
    Tool("shorts_create", ("shorts", "create"),
         "Give each approved candidate its own workspace and EDL; nothing is re-transcribed.",
         (_ws(flag=None), Param("only", kind="array", flag="--only"),
          Param("reframe", flag="--reframe"))),
    Tool("image_status", ("image", "status"),
         "Which image APIs this CLI can reach. It cannot see your own tools."),
    Tool("image_prompt", ("image", "prompt"),
         "The guarded prompt to pass to an image tool, verbatim: background only, no text.",
         (Param("prompt", flag="--prompt", required=True,
                description="What the background should show."),),
         json_flag=False),
    Tool("image_capabilities", ("image", "capabilities"),
         "Record what this session can do about imagery, and which source was chosen.",
         (_ws(flag=None),
          Param("chosen_source", flag="--chosen-source", required=True,
                description="existing_asset, video_frame, canva, chatgpt_native, openai_api, "
                "gemini_api or local_composition."),
          Param("reason", flag="--reason", required=True,
                description="Why this source serves the edit, not that it was available."),
          Param("native_imagegen", flag="--native-imagegen",
                description="available or unavailable, from your own tool list."),
          Param("canva", flag="--canva", description="available or unavailable."))),
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
          Param("first_frame_note", flag="--first-frame-note"),
          Param("hook_variants", kind="boolean", flag="--hook-variants",
                description="Also deliver full-length opening variants."),
          Param("max_size_mb", kind="number", flag="--max-size-mb",
                description="Re-encode a video above this many MB under it, audio copied."),
          Param("description_template", kind="boolean", flag="--description-template",
                description="Write publish.template.md: the post description's parts."),
          Param("name", flag="--name",
                description="What the videos are called before -FINAL (NAME-FINAL.mp4)."),
          Param("music_variants", kind="boolean", negative="--one-audio",
                description="With a music bed, also deliver NAME-FINAL-no-music.mp4 "
                "(default true)."))),
    Tool("export_timeline", ("export",), "Write the cut as an NLE timeline.",
         (_ws(flag=None), Param("format", flag="--format"), Param("output", flag="--output"))),
    Tool("platforms", ("platforms",), "Publishing destinations and their reserved zones."),
    Tool("profiles", ("profiles",), "The output profiles and brand profiles available."),
    Tool("doctor", ("doctor",), "Check this machine can produce a correct video."),
    Tool("version", ("version",), "The engine's version, and whether its parts agree.",
         json_flag=False),
)  # fmt: skip

BY_NAME = {tool.name: tool for tool in TOOLS}

#: Commands that are deliberately not tools, each with its reason. A new CLI
#: command has to be given a tool or a line here: the test that compares this
#: table with the CLI fails until one of the two is done.
NOT_TOOLS: dict[tuple[str, ...], str] = {
    ("remotion-license", "attest"): "declaring the Remotion licence is the user's own act",
    ("remotion-license", "refresh"): "re-confirming the Remotion licence is the user's own act",
    ("remotion-license", "revoke"): "withdrawing the Remotion licence is the user's own act",
    ("fetch",): "a download needs the user's statement of their right to edit the recording",
    ("image", "plate"): "a cloud image call needs the user's consent",
    ("image", "register"): "registering an image as usable is the user's statement about it",
    ("edit",): "the one-shot pipeline runs outside the stages and their gates",
    ("mcp", "serve"): "the server itself",
    ("mcp", "tools"): "the server's own listing; a client asks the protocol",
}

#: Options a tool's command has and the tool does not offer, each with its
#: reason. `--json` and `--help` are left out everywhere and are not listed.
OMITTED_OPTIONS: dict[str, dict[str, str]] = {
    "workflow_status": {"--workspace": "the same input as the positional workspace"},
    "workflow_resume": {"--workspace": "the same input as the positional workspace"},
    "config_init": {"--defaults": "a tool call has no terminal, so nothing is asked"},
    "motion_sfx": {"--licensed": "accepted for compatibility; it does nothing"},
    "motion_film_spec": {"--allow-brand-upload": "uploading brand files is the user's consent"},
    "render": {"--remotion-license": "a licence statement belongs to Stage 0, not to a render"},
    "doctor": {
        "--install-ffmpeg": "installing software on the machine is the user's decision",
        "--install-remotion": "installing Remotion happens under the user's licence declaration",
    },
}


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


#: Above the longest step a command takes on its own (a render stops at four
#: hours), so this only ends a child that will never answer.
DEFAULT_TIMEOUT_S = 6 * 3600
TIMEOUT_ENV = "SOCIAL_VIDEO_MCP_TIMEOUT"


def tool_timeout() -> float:
    """Seconds one tool call may run: ``SOCIAL_VIDEO_MCP_TIMEOUT`` or six hours."""
    raw = os.environ.get(TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 0.0
    if seconds <= 0:
        raise ToolInputError(f"{TIMEOUT_ENV} is a number of seconds above zero, got {raw!r}")
    return seconds


def run_cli(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """One CLI command in a child process, with plain, wide output."""
    env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "400"}
    return subprocess.run(
        [sys.executable, "-m", "social_video", *argv],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=tool_timeout(),
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
    try:
        proc = runner(argv)
    except ToolInputError as exc:
        return {"ok": False, "error": str(exc)}
    except subprocess.TimeoutExpired as exc:
        # The server stays up and says so; a hung child must not hang the agent.
        return {
            "ok": False,
            "command": argv,
            "error": f"timed out after {exc.timeout:.0f} s; raise {TIMEOUT_ENV} if the "
            "command needs longer",
        }
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
