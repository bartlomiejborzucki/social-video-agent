"""Sound under the edit: the music bed."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape

from social_video.cli._apps import audio_app
from social_video.cli._common import _guard, console

#: What the bed is for, when the caller does not say.
DEFAULT_REASON = "Music bed under the whole edit, ducked under the voice."


@audio_app.command("bed")
def audio_bed(
    file: Path | None = typer.Argument(
        None, help="The music file: one you hold the rights to. Omit it with --remove."
    ),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    gain_db: float = typer.Option(
        -20.0, "--gain-db", help="Level under the voice, -60 to 0. Above -12 QA warns."
    ),
    duck: bool = typer.Option(
        True, "--duck/--no-duck", help="Pull the bed down while someone speaks."
    ),
    loop: bool = typer.Option(
        False, "--loop", help="Repeat a track shorter than the edit; only one built to loop."
    ),
    start_at: float = typer.Option(0.0, "--start-at", help="Seconds into the track to start."),
    fade_in: float = typer.Option(0.5, "--fade-in"),
    fade_out: float = typer.Option(1.5, "--fade-out"),
    reason: str = typer.Option(DEFAULT_REASON, "--reason", help="Why this bed, in one line."),
    license_note: str = typer.Option(
        "", "--license-note", help="Where the track comes from; recorded with the render."
    ),
    remove: bool = typer.Option(False, "--remove", help="Take the bed out of the edit."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Put a music bed under the edit, or take it out.

    Writes `audio_bed` into edl.json after checking that the file has sound
    and covers the edit. The file stays where it is and is never fetched; the
    rights to it are yours. A recompile keeps the bed. With a bed in the edit,
    delivery also makes a version without it.
    """
    from social_video.errors import ValidationError
    from social_video.ffmpeg.probe import probe
    from social_video.paths import normalize_user_path
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.edl import EDL, AudioBed
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run() -> tuple[EDL, float | None]:
        if not ws.edl.is_file():
            raise ValidationError(f"no edl.json in {ws.root}; compile the edit first")
        edl = load_artifact(EDL, ws.edl)
        if remove:
            if file is not None:
                raise ValidationError("--remove takes no file")
            edl.audio_bed = None
            save_artifact(edl, ws.edl)
            return edl, None
        if file is None:
            raise ValidationError("name the music file, or pass --remove")
        path = normalize_user_path(file, must_exist=True)
        info = probe(path)
        if not info.has_audio:
            raise ValidationError(f"{path.name} has no audio stream")
        covers = max(0.0, info.duration - start_at)
        if not loop and covers + 0.05 < edl.total_duration:
            raise ValidationError(
                f"{path.name} covers {covers:.2f}s from {start_at:.2f}s but the edit is "
                f"{edl.total_duration:.2f}s. Use a longer track, or pass --loop for one "
                "built to loop."
            )
        edl.audio_bed = AudioBed(
            path=str(path),
            gain_db=gain_db,
            start_at=start_at,
            loop=loop,
            fade_in=fade_in,
            fade_out=fade_out,
            duck=duck,
            license_confirmed=bool(license_note.strip()),
            license_note=license_note.strip(),
            reason=reason.strip() or DEFAULT_REASON,
        )
        save_artifact(edl, ws.edl)
        return edl, covers

    edl, covers = _guard(run)
    bed = edl.audio_bed
    if as_json:
        console.print_json(
            data={
                "edl": str(ws.edl),
                "audio_bed": None if bed is None else bed.model_dump(mode="json"),
                "covers_s": None if covers is None else round(covers, 2),
                "edit_s": round(edl.total_duration, 2),
            }
        )
        return
    if bed is None:
        console.print(f"[green]removed[/green] the music bed from {ws.edl}", soft_wrap=True)
        return
    console.print(
        f"[green]bed[/green] {escape(Path(bed.path).name)} at {bed.gain_db:g} dB, "
        f"{'ducked' if bed.duck else 'not ducked'}"
        f"{', looped' if bed.loop else ''} -> {ws.edl}",
        soft_wrap=True,
    )
    console.print(
        "[dim]delivery will make the edit with this bed and, as NAME-FINAL-no-music, "
        "without it[/dim]",
        soft_wrap=True,
    )
