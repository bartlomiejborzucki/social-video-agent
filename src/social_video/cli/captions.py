"""Caption translation and correction. Nothing here calls a service."""

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


@captions_app.command("fix")
def captions_fix(
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    at: float = typer.Option(..., "--at", help="Output time the caption is on screen, seconds."),
    old: str = typer.Option(..., "--from", help="The word(s) to replace, as captioned."),
    new: str = typer.Option(..., "--to", help="What the caption should say instead."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Correct the words of one caption; its timing stays as recognised.

    Updates the cue and its words (the active-word highlight draws from the
    words), then rewrites the track's SRT, VTT and ASS. The track is marked
    corrected, so a later rebuild does not silently discard the fix.
    """
    from social_video.captions.ass import write_ass
    from social_video.captions.fix import fix_words
    from social_video.captions.srt import write_srt, write_vtt
    from social_video.schemas.base import save_artifact

    def run():
        _ws, edl, track, brand = _loaded(workspace_dir)
        fixed, change = fix_words(track, at=at, old=old, new=new, case=brand.captions.case)
        base = Path(edl.captions)
        save_artifact(fixed, base.with_suffix(".json"))
        write_srt(fixed, base.with_suffix(".srt"))
        write_vtt(fixed, base.with_suffix(".vtt"))
        write_ass(
            fixed,
            brand.captions,
            base.with_suffix(".ass"),
            width=edl.output_width,
            height=edl.output_height,
            font_name=brand.captions.font_family or None,
        )
        return change, base

    change, base = _guard(run)
    if as_json:
        console.print_json(data={"cue": change.cue, "before": change.before, "after": change.after})
        return
    console.print(f"cue {change.cue}: {change.before!r} -> {change.after!r}", soft_wrap=True)
    for suffix in (".json", ".srt", ".vtt", ".ass"):
        console.print(f"  [green]written[/green] {base.with_suffix(suffix)}", soft_wrap=True)
