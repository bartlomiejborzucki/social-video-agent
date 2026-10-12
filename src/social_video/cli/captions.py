"""Caption translation. The agent translates; nothing here calls a service."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from social_video.cli._apps import captions_app
from social_video.cli._common import _guard, console


def _loaded(workspace_dir: Path):
    from social_video.errors import ValidationError
    from social_video.pipeline import load_workspace_brand
    from social_video.schemas.base import load_artifact
    from social_video.schemas.captions import CaptionTrack
    from social_video.schemas.edl import EDL
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)
    if not ws.edl.is_file():
        raise ValidationError(f"no EDL at {ws.edl}")
    edl = load_artifact(EDL, ws.edl)
    if not edl.captions:
        raise ValidationError("the edit has no captions to translate; build them first")
    track_path = Path(edl.captions).with_suffix(".json")
    if not track_path.is_file():
        raise ValidationError(f"caption data is missing at {track_path}")
    return ws, edl, load_artifact(CaptionTrack, track_path), load_workspace_brand(ws)


@captions_app.command("translate")
def captions_translate(
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    to: str = typer.Option(..., "--to", help="Language code, e.g. en, de, pt-BR."),
    force: bool = typer.Option(False, "--force", help="Overwrite a file already started."),
) -> None:
    """Write the cues for the agent to translate, with the limits each line keeps."""
    from social_video.captions.translate import (
        check_language,
        export_for_translation,
        translated_paths,
    )
    from social_video.errors import ValidationError
    from social_video.fsutil import atomic_write_bytes

    def run():
        ws, edl, track, brand = _loaded(workspace_dir)
        language = check_language(to)
        target = translated_paths(ws.captions, edl.name, language)["request"]
        if target.is_file() and not force:
            raise ValidationError(f"{target} exists; fill it in, or pass --force to start over")
        data = export_for_translation(track, language, brand.captions)
        atomic_write_bytes(target, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode())
        return target, len(track.cues)

    target, count = _guard(run)
    console.print(f"{count} cue(s) to translate in [green]{target}[/green]", soft_wrap=True)
    console.print("Fill in every `translation`, then run `captions apply`.")


@captions_app.command("apply")
def captions_apply(
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    to: str = typer.Option(..., "--to", help="Language code the file translates into."),
    file: Path | None = typer.Option(None, "--file", help="Default: the file `translate` wrote."),
    max_chars: int | None = typer.Option(
        None, "--max-chars", help="Line limit for this language (default: the contract's)."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Check the translation and write its caption track, ASS, SRT and VTT."""
    from social_video.captions.ass import write_ass
    from social_video.captions.srt import write_srt, write_vtt
    from social_video.captions.translate import apply_translation, check_language, translated_paths
    from social_video.errors import ValidationError
    from social_video.schemas.base import save_artifact

    def run():
        ws, edl, track, brand = _loaded(workspace_dir)
        language = check_language(to)
        paths = translated_paths(ws.captions, edl.name, language)
        source = file or paths["request"]
        if not source.is_file():
            raise ValidationError(f"no translation at {source}; run `captions translate` first")
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValidationError(f"{source} is not valid JSON: {exc}") from exc
        translated = apply_translation(
            track, data, brand.captions, language=language, max_chars=max_chars
        )
        save_artifact(translated, paths["json"])
        write_srt(translated, paths["srt"])
        write_vtt(translated, paths["vtt"])
        write_ass(
            translated,
            brand.captions,
            paths["ass"],
            width=edl.output_width,
            height=edl.output_height,
            font_name=brand.captions.font_family or None,
        )
        return translated, paths

    translated, paths = _guard(run)
    if as_json:
        console.print_json(
            data={k: str(v) for k, v in paths.items()} | {"cues": len(translated.cues)}
        )
        return
    console.print(f"{len(translated.cues)} cue(s) in {translated.language}; word timings estimated")
    for key in ("json", "ass", "srt", "vtt"):
        console.print(f"  [green]written[/green] {paths[key]}", soft_wrap=True)
    console.print(f"Deliver it with `deliver --language {translated.language}`.")
