"""Motion accents: found by the code, accepted by the agent."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape

from social_video.cli._apps import motion_app
from social_video.cli._common import _guard, console


def _content_first(ws) -> bool:
    from social_video.schemas.base import load_artifact
    from social_video.schemas.config import BrandContract

    if not ws.brand_contract.is_file():
        return False
    return load_artifact(BrandContract, ws.brand_contract).opening.opening_policy == "content_first"


def _energy(ws):
    from social_video.motion.energy import energy_preset
    from social_video.schemas.base import load_artifact
    from social_video.schemas.config import BrandContract

    if ws.brand_contract.is_file():
        return energy_preset(load_artifact(BrandContract, ws.brand_contract).brand.motion_energy)
    return energy_preset("lively")


@motion_app.command("suggest")
def motion_suggest(
    source: Path = typer.Argument(..., help="Source video the EDL cuts."),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    energy: str | None = typer.Option(
        None, "--energy", help="calm, lively or bold (default: the contract's)."
    ),
    model: str = typer.Option("small", "--model"),
    language: str | None = typer.Option(None, "--language"),
    hook_punch: bool = typer.Option(
        False,
        "--hook-punch",
        help="Also propose a 1.16 push-in on the first key word at 1.0-1.5 s.",
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List where the edit should move -- hook card, figures, steps, punch-ins, transitions.

    Sized to the energy level and spaced out; on a licensed music bed, punch-ins
    land on its beats. Nothing changes until you run `motion accept`.
    """
    from social_video.analysis.beats import detect_beats
    from social_video.errors import ValidationError
    from social_video.motion.energy import energy_preset
    from social_video.motion.suggest import find_accents
    from social_video.pipeline import stage_transcribe
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.edl import EDL
    from social_video.schemas.transcript import Transcript
    from social_video.transcribe.base import TranscriptionOptions
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        if not ws.edl.is_file():
            raise ValidationError(f"no EDL at {ws.edl}; accents are placed on the cut")
        edl = load_artifact(EDL, ws.edl)
        preset = energy_preset(energy) if energy else _energy(ws)
        transcript = stage_transcribe(
            source, ws, options=TranscriptionOptions(model=model, language=language)
        )
        beats = []
        if edl.audio_bed is not None:
            beats = detect_beats(
                Path(edl.audio_bed.path),
                start_at=edl.audio_bed.start_at,
                duration=edl.total_duration,
            )
        others = {
            t.source_id: t
            for t in (load_artifact(Transcript, p) for p in sorted(ws.transcripts.glob("*.json")))
            if t.source_id != transcript.source_id
        }
        opening = None
        if ws.source_manifest.is_file():
            from social_video.motion.opening import opening_in_point
            from social_video.schemas.source import SourceManifest

            heard = {transcript.source_id: transcript, **others}
            opening = opening_in_point(
                edl, load_artifact(SourceManifest, ws.source_manifest), heard
            )
        found = find_accents(
            transcript, edl, preset, beats=beats, content_first=_content_first(ws),
            transcripts=others, opening=opening, hook_punch=hook_punch,
        )  # fmt: skip
        save_artifact(found, ws.accent_candidates)
        return found

    found = _guard(run)
    if as_json:
        console.print_json(found.to_json())
        return
    console.print(f"energy [bold]{found.energy}[/bold]{' , on the beat' if found.on_beat else ''}")
    for c in found.candidates:
        move = (
            "element"
            if c.element
            else "punch-in"
            if c.punch_in
            else "framing"
            if c.range_zoom
            else "in-point"
            if c.range_start
            else "transition"
        )
        what = c.element.type.value if c.element else move
        colour = "green" if c.confidence == "high" else "yellow"
        console.print(
            f"  {c.id}  [{colour}]{c.confidence:6}[/{colour}] {c.kind.value:10} {what:10} "
            f"@{c.at:6.2f}s  {escape(c.reason)}"
        )
    console.print(f"\n[green]written[/green] {ws.accent_candidates}", soft_wrap=True)


@motion_app.command("accept")
def motion_accept(
    ids: list[str] = typer.Argument(None, help="Accent ids, e.g. acc-001 acc-004."),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    kind: list[str] = typer.Option([], "--kind", help="Accept every accent of this kind."),
    confidence: str | None = typer.Option(None, "--confidence"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Add the chosen accents to motion-plan.json."""
    from social_video.errors import ValidationError
    from social_video.motion.suggest import accept_accents, apply_range_starts, apply_range_zooms
    from social_video.schemas.base import load_artifact, save_artifact, save_artifacts_atomically
    from social_video.schemas.edl import EDL
    from social_video.schemas.motion import AccentCandidateSet, MotionPlan
    from social_video.schemas.plan import EditPlan
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        if not ws.accent_candidates.is_file():
            raise ValidationError(f"no accents at {ws.accent_candidates}; run `motion suggest`")
        found = load_artifact(AccentCandidateSet, ws.accent_candidates)
        chosen = list(ids or []) + [
            c.id
            for c in found.candidates
            if c.kind.value in kind and (confidence is None or c.confidence == confidence)
        ]
        if not chosen and kind and not ids:
            return None, []
        jumps = [c for c in found.candidates if c.id in chosen and c.range_zoom is not None]
        starts = [c for c in found.candidates if c.id in chosen and c.range_start is not None]
        skipped: list[str] = []
        if jumps or starts:
            edl = load_artifact(EDL, ws.edl)
            edit = load_artifact(EditPlan, ws.edit_plan) if ws.edit_plan.is_file() else None
            edl, edit, notes = apply_range_zooms(edl, edit, jumps)
            edl, edit, more_notes = apply_range_starts(edl, edit, starts)
            notes += more_notes
            writes = {ws.edl: edl, **({ws.edit_plan: edit} if edit is not None else {})}
            save_artifacts_atomically(writes)
            skipped += notes
        plan = load_artifact(MotionPlan, ws.motion_plan) if ws.motion_plan.is_file() else None
        updated, more = accept_accents(plan, found, chosen)
        save_artifact(updated, ws.motion_plan)
        return updated, skipped + more

    updated, skipped = _guard(run)
    if as_json:
        console.print_json(
            data={
                "elements": len(updated.elements) if updated else 0,
                "punch_ins": len(updated.punch_ins) if updated else 0,
                "transitions": len(updated.transitions) if updated else 0,
                "skipped": skipped,
            }
        )
        return
    if updated is None:
        console.print("No accents of that kind.")
        return
    console.print(
        f"motion plan: {len(updated.elements)} graphic(s), {len(updated.punch_ins)} punch-in(s), "
        f"{len(updated.transitions)} transition(s) -> [green]{ws.motion_plan}[/green]",
        soft_wrap=True,
    )
    for line in skipped:
        applied = " on plan item " in line or " start at " in line
        mark = "[green]applied[/green]" if applied else "[yellow]note[/yellow]"
        console.print(f"  {mark} {escape(line)}", soft_wrap=True)


@motion_app.command("sfx")
def motion_sfx(
    library_dir: Path = typer.Argument(..., help="Your folder of sound effects."),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    licensed: bool = typer.Option(
        False,
        "--licensed",
        help="Accepted for compatibility; effects no longer need a rights declaration.",
        hidden=True,
    ),
    gain_db: float = typer.Option(-10.0, "--gain-db"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Put a whoosh under each transition and a pop under each graphic, from your library."""
    from social_video.motion.sfx import sync_sfx
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.edl import EDL
    from social_video.schemas.motion import MotionPlan
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        edl = load_artifact(EDL, ws.edl)
        plan = load_artifact(MotionPlan, ws.motion_plan)
        updated, added = sync_sfx(edl, plan, library_dir, gain_db=gain_db)
        save_artifact(updated, ws.edl)
        return added

    added = _guard(run)
    if as_json:
        console.print_json(data=[effect.model_dump(mode="json") for effect in added])
        return
    for effect in added:
        console.print(f"  [{effect.at:6.2f}s] {Path(effect.path).name}  {escape(effect.reason)}")
    console.print(f"\n{len(added)} effect(s) added to [green]{ws.edl}[/green]", soft_wrap=True)


@motion_app.command("variants")
def motion_variants(
    texts: list[str] = typer.Option(
        [], "--text", help="One opening line per variant (repeat), or use --from-brief."
    ),
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    from_brief: bool = typer.Option(
        False,
        "--from-brief",
        help="Up to three first captions from the brief: its on-screen text, the first "
        "spoken sentence, and a question.",
    ),
    seconds: float | None = typer.Option(
        None, "--seconds", help="Render only the first N seconds (a quick A/B look)."
    ),
    quality: str = typer.Option("preview", "--quality"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Render one version per opening line, to test which hook holds viewers.

    Under a content-first opening a variant changes the first caption, never
    adds a card; with `opening_policy: free` it is the hook card's text.
    """
    from social_video.captions.ass import write_ass
    from social_video.errors import ValidationError
    from social_video.motion.hook_variants import (
        HookVariant,
        HookVariantSet,
        Proposal,
        head_of,
        variants_from_brief,
        with_first_caption,
    )
    from social_video.motion.review import with_hook
    from social_video.pipeline import load_workspace_artifacts, load_workspace_brand, stage_render
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.brief import Brief
    from social_video.schemas.captions import CaptionTrack
    from social_video.schemas.motion import MotionPlan
    from social_video.schemas.workflow import Renderer
    from social_video.workflow import load_workflow
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        state = load_workflow(ws)
        if state.renderer is not Renderer.REMOTION:
            raise ValidationError(
                "hook variants are drawn by Remotion; switch with `workflow renderer`"
            )
        proposals = [Proposal(f"tekst-{n}", t) for n, t in enumerate(texts, start=1)]
        if from_brief:
            if not ws.brief.is_file():
                raise ValidationError(f"no brief at {ws.brief}; run `brief import` first")
            proposals += variants_from_brief(load_artifact(Brief, ws.brief))
        if not proposals:
            raise ValidationError("give --text lines or --from-brief")
        manifest, edl = load_workspace_artifacts(ws)
        plan = load_artifact(MotionPlan, ws.motion_plan)
        content_first = _content_first(ws)
        caption_path = Path(edl.captions) if edl.captions else None
        track = (
            load_artifact(CaptionTrack, caption_path.with_suffix(".json"))
            if caption_path and caption_path.with_suffix(".json").is_file()
            else None
        )
        if content_first and track is None:
            raise ValidationError("hook variants change the first caption; build captions first")
        brand = load_workspace_brand(ws)
        made = []
        for proposal in proposals:
            variant_edl, variant_plan = edl, plan
            captions = caption_path
            if content_first:
                assert track is not None
                variant = with_first_caption(track, proposal.text)
                captions = ws.captions / f"hook-{proposal.name}.ass"
                save_artifact(variant, captions.with_suffix(".json"))
                write_ass(
                    variant,
                    brand.captions,
                    captions,
                    width=edl.output_width,
                    height=edl.output_height,
                    font_name=brand.captions.font_family,
                )
            else:
                variant_plan = with_hook(plan, proposal.text)
            if seconds is not None:
                variant_edl, head_plan = head_of(variant_edl, variant_plan, seconds)
                variant_plan = head_plan or variant_plan
            suffix = f"-{seconds:g}s" if seconds is not None else ""
            output = ws.previews / f"hook-{proposal.name}{suffix}.mp4"
            stage_render(
                variant_edl,
                manifest,
                ws,
                quality=quality,
                captions=captions,
                output=output,
                renderer=Renderer.REMOTION,
                motion_plan=variant_plan,
                remotion_license_attestation=state.remotion_license_attestation,
            )
            made.append(
                HookVariant(
                    name=proposal.name, text=proposal.text, file=str(output), seconds=seconds
                )
            )
        registry = ws.analysis / "hook-variants.json"
        known = load_artifact(HookVariantSet, registry).variants if registry.is_file() else []
        kept = [v for v in known if v.file not in {m.file for m in made}]
        save_artifact(HookVariantSet(variants=[*kept, *made]), registry)
        return made

    made = _guard(run)
    if as_json:
        console.print_json(data={"variants": [v.model_dump(mode="json") for v in made]})
        return
    for variant in made:
        console.print(
            f"[green]rendered[/green] {variant.name}: {escape(variant.text)} -> {variant.file}",
            soft_wrap=True,
        )


@motion_app.command("sheet")
def motion_review_sheet(
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    video: Path | None = typer.Option(None, "--video", help="Render to review (default: preview)."),
) -> None:
    """One labelled frame per graphic, punch-in and transition, for Stage 3 review."""
    from social_video.motion.film import load_registry
    from social_video.motion.review import motion_sheet
    from social_video.schemas.base import load_artifact
    from social_video.schemas.motion import MotionPlan
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)
    target = video or ws.previews / "preview.mp4"
    films = [
        (s.start_in_output + min(0.6, s.duration * 0.5), f"motion film {s.scene_id}")
        for s in load_registry(ws).segments
    ]
    verdicts = None
    if ws.motion_qa.is_file():
        from social_video.qa.motion import moment_verdicts
        from social_video.schemas.qa import QAReport

        report = load_artifact(QAReport, ws.motion_qa)
        verdicts = lambda moments: moment_verdicts(moments, report)  # noqa: E731
    path = _guard(
        lambda: motion_sheet(
            target,
            load_artifact(MotionPlan, ws.motion_plan),
            ws.qa / "motion-sheet.png",
            extra=films,
            verdicts=verdicts,
        )
    )
    console.print(f"[green]written[/green] {path}", soft_wrap=True)


@motion_app.command("qa")
def motion_qa(
    workspace_dir: Path = typer.Option(..., "--workspace", "-w"),
    video: Path | None = typer.Option(
        None, "--video", help="Render to measure faces on (default: the base render or preview)."
    ),
    faces: bool = typer.Option(True, "--faces/--no-faces", help="Measure faces under graphics."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Measure every graphic: time to read it, captions and faces it covers, rhythm."""
    from social_video.errors import ValidationError
    from social_video.motion.film import load_registry
    from social_video.qa.motion import check_motion, faces_from_video
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.captions import CaptionTrack
    from social_video.schemas.config import BrandContract
    from social_video.schemas.edl import EDL
    from social_video.schemas.motion import MotionPlan
    from social_video.workspace.layout import Workspace

    ws = Workspace.at(workspace_dir)

    def run():
        if not ws.edl.is_file():
            raise ValidationError(f"no EDL at {ws.edl}")
        edl = load_artifact(EDL, ws.edl)
        plan = load_artifact(MotionPlan, ws.motion_plan) if ws.motion_plan.is_file() else None
        contract = (
            load_artifact(BrandContract, ws.brand_contract) if ws.brand_contract.is_file() else None
        )
        track = None
        if edl.captions and Path(edl.captions).with_suffix(".json").is_file():
            track = load_artifact(CaptionTrack, Path(edl.captions).with_suffix(".json"))
        if plan is not None:
            from social_video.motion.stickers import anchor_to_words

            plan, _notes = anchor_to_words(plan, track)
        # The Remotion base render has no graphics over the faces.
        base = ws.cache / "remotion" / "base-preview.mp4"
        frames = video or (base if base.is_file() else ws.previews / "preview.mp4")
        provider, note = None, "--no-faces"
        if faces:
            if frames.is_file():
                try:
                    provider = faces_from_video(frames)
                except Exception as exc:  # no model offline, an unreadable file
                    note = f"face detection unavailable ({exc})"
            else:
                note = f"no render at {frames}"
        report = check_motion(
            edl, plan, contract, output=str(frames), captions=track,
            film_segments=load_registry(ws).segments, faces=provider, faces_note=note,
        )  # fmt: skip
        save_artifact(report, ws.motion_qa)
        return report

    report = _guard(run)
    if as_json:
        console.print_json(report.to_json())
        return
    for check in report.checks:
        mark = "[green]ok[/green]  " if check.passed else "[yellow]warn[/yellow]"
        console.print(f"  {mark} {escape(check.name)}: {escape(check.message)}", soft_wrap=True)
    console.print(f"[green]written[/green] {ws.motion_qa}", soft_wrap=True)
