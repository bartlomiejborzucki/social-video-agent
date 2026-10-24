"""Render opening variants without touching the edit they vary.

The pure parts live in ``hook_variants``; this module loads the workspace,
renders each variant into its own files and records the set. The workspace
EDL, motion plan, captions and the main Remotion base are never written.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from social_video.errors import ValidationError
from social_video.imaging import sha256_file
from social_video.motion.hook_variants import (
    BUILT_AXES,
    PREVIEW_SECONDS,
    OpeningVariant,
    OpeningVariantSet,
    Proposal,
    VariantAxis,
    VariantBase,
    VariantChange,
    audio_sha256,
    first_shot_edl,
    head_of,
    load_variant_set,
    opening_text_end,
    parse_shot,
    shift_plan,
    variant_names,
    variants_from_brief,
    verbatim_first_caption,
    with_opening_text,
)
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.edl import EDL
from social_video.schemas.motion import MotionElementType, MotionPlan
from social_video.schemas.transcript import Transcript
from social_video.workspace.layout import Workspace

log = logging.getLogger(__name__)


@dataclass
class VariantRequest:
    axis: VariantAxis | None = None
    texts: list[str] = field(default_factory=list)
    from_brief: bool = False
    first_shots: list[str] = field(default_factory=list)
    pickups: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    only: list[str] = field(default_factory=list)
    seconds: float | None = PREVIEW_SECONDS
    quality: str = "preview"


def registry_path(ws: Workspace) -> Path:
    return ws.analysis / "hook-variants.json"


def _content_first(ws: Workspace) -> bool:
    from social_video.schemas.config import BrandContract

    if not ws.brand_contract.is_file():
        return False
    return load_artifact(BrandContract, ws.brand_contract).opening.opening_policy == "content_first"


def _proposals(
    ws: Workspace, request: VariantRequest, known: OpeningVariantSet | None
) -> tuple[VariantAxis, list[tuple[Proposal, str]]]:
    """The variants to make, each with its hypothesis."""
    if request.only:
        if known is None:
            raise ValidationError("no variants recorded yet; make previews first")
        if request.axis is not None and request.axis is not known.axis:
            raise ValidationError(
                f"the recorded variants vary {known.axis.value}, not {request.axis.value}"
            )
        picked = []
        for name in request.only:
            variant = known.find(name)
            if variant is None:
                raise ValidationError(f"no recorded variant {name!r}")
            if variant.needs_pickup:
                raise ValidationError(
                    f"variant {name!r} needs a pickup recorded first: {variant.needs_pickup}"
                )
            picked.append((Proposal(name, variant.text, variant.first_shot), variant.hypothesis))
        return known.axis, picked

    axis = request.axis or (
        VariantAxis.FIRST_SHOT if request.first_shots or request.pickups else VariantAxis.TEXT
    )
    if axis not in BUILT_AXES:
        raise ValidationError(f"the {axis.value} axis is not built yet; vary text or first_shot")
    if axis is VariantAxis.TEXT:
        if request.first_shots or request.pickups:
            raise ValidationError("--first-shot and --pickup belong to the first_shot axis")
        lines = list(request.texts)
        if request.from_brief:
            from social_video.schemas.brief import Brief

            if not ws.brief.is_file():
                raise ValidationError(f"no brief at {ws.brief}; run `brief import` first")
            lines += variants_from_brief(load_artifact(Brief, ws.brief))
        if not lines:
            raise ValidationError("give --text lines or --from-brief")
        specs = [("text", line) for line in lines]
    else:
        if request.texts or request.from_brief:
            raise ValidationError("--text and --from-brief belong to the text axis")
        specs = [("shot", s) for s in request.first_shots] + [
            ("pickup", p) for p in request.pickups
        ]
        if not specs:
            raise ValidationError("give --first-shot SOURCE:START-END or --pickup per variant")
    if request.hypotheses and len(request.hypotheses) != len(specs):
        raise ValidationError(
            f"{len(specs)} variant(s) but {len(request.hypotheses)} --hypothesis; "
            "give one per variant, in order"
        )
    hypotheses = request.hypotheses or [""] * len(specs)
    proposals = []
    for name, (kind, value), hypothesis in zip(
        variant_names(len(specs)), specs, hypotheses, strict=True
    ):
        if kind == "text":
            proposals.append((Proposal(name, text=value), hypothesis))
        elif kind == "shot":
            parse_shot(value)
            proposals.append((Proposal(name, first_shot=value), hypothesis))
        else:
            proposals.append((Proposal(name, pickup=value), hypothesis))
    return axis, proposals


def _transcripts(ws: Workspace, edl: EDL) -> list[Transcript]:
    found = []
    for rng in edl.ranges:
        path = ws.transcript_for(rng.effective_audio_source, rng.audio_track)
        if path.is_file() and all(t.source_id != rng.effective_audio_source for t in found):
            found.append(load_artifact(Transcript, path))
    return found


def make_variants(ws: Workspace, request: VariantRequest) -> tuple[OpeningVariantSet, list[str]]:
    """Render (or record) the requested variants; returns the set and notes for the user."""
    from social_video.captions.ass import write_ass
    from social_video.motion.review import with_hook
    from social_video.pipeline import (
        load_workspace_artifacts,
        load_workspace_brand,
        stage_captions,
        stage_render,
    )
    from social_video.schemas.workflow import Renderer
    from social_video.workflow import load_workflow

    state = load_workflow(ws)
    if state.renderer is not Renderer.REMOTION:
        raise ValidationError(
            "opening variants are drawn by Remotion; switch with `workflow renderer`"
        )
    registry = registry_path(ws)
    known = load_variant_set(registry)
    axis, proposals = _proposals(ws, request, known)
    notes: list[str] = []
    if len(proposals) > 2 and not request.only:
        notes.append(f"{len(proposals)} variants: more than two is harder to compare and to watch")
    if any(not h for _, h in proposals):
        notes.append("a variant has no --hypothesis: say what each one is meant to test")

    manifest, edl = load_workspace_artifacts(ws)
    plan = load_artifact(MotionPlan, ws.motion_plan)
    content_first = _content_first(ws)
    caption_path = Path(edl.captions) if edl.captions else None
    caption_json = caption_path.with_suffix(".json") if caption_path else None
    track = (
        load_artifact(CaptionTrack, caption_json)
        if caption_json is not None and caption_json.is_file()
        else None
    )
    brand = load_workspace_brand(ws)
    base = VariantBase(
        edl_sha256=sha256_file(ws.edl),
        motion_plan_sha256=sha256_file(ws.motion_plan),
        captions_sha256=sha256_file(caption_json)
        if caption_json and caption_json.is_file()
        else None,
    )
    if known is not None and known.base is not None and known.base != base and request.only:
        raise ValidationError(
            "the edit changed since the previews were made; make the previews again"
        )

    made: list[OpeningVariant] = []
    for proposal, hypothesis in proposals:
        first = edl.ranges[0]
        if proposal.pickup:
            made.append(
                OpeningVariant(
                    name=proposal.name, hypothesis=hypothesis, needs_pickup=proposal.pickup,
                    changes=[VariantChange(element="first range", before=_range(first),
                                           after=f"to record: {proposal.pickup}")],
                    shared=["nothing rendered until the pickup is recorded"],
                )
            )  # fmt: skip
            continue
        variant_edl, variant_plan, captions = edl, plan, caption_path
        changes: list[VariantChange] = []
        shared: list[str] = []
        warnings: list[str] = []
        shown_as = None
        own_edl = own_plan = own_captions = None
        if axis is VariantAxis.TEXT:
            text = proposal.text
            if not content_first:
                hook = next(
                    (e for e in plan.elements if e.type is MotionElementType.HOOK_CARD), None
                )
                variant_plan = with_hook(plan, text)
                shown_as = "hook_card"
                changes.append(
                    VariantChange(element="hook card", before=hook.text if hook else "", after=text)
                )
                shared += ["captions", "every cut", "audio"]
            else:
                if track is None:
                    raise ValidationError(
                        "a content-first opening line needs captions; build them first"
                    )
                said = verbatim_first_caption(track, text)
                before = track.cues[0].text if track.cues else ""
                if said is not None:
                    shown_as = "caption"
                    if said is not track:
                        captions = ws.captions / f"hook-{proposal.name}.ass"
                        save_artifact(said, captions.with_suffix(".json"))
                        write_ass(
                            said, brand.captions, captions,
                            width=edl.output_width, height=edl.output_height,
                            font_name=brand.captions.font_family,
                        )  # fmt: skip
                        own_captions = str(captions.with_suffix(".json"))
                    changes.append(
                        VariantChange(element="first caption", before=before, after=text)
                    )
                    shared += ["captions after the first", "every cut", "audio"]
                else:
                    shown_as = "on_screen_text"
                    variant_plan = with_opening_text(plan, text, end=opening_text_end(track))
                    changes.append(
                        VariantChange(element="on-screen opening text", before="", after=text)
                    )
                    shared += ["every caption (the transcript)", "every cut", "audio"]
                    notes.append(
                        f"{proposal.name}: “{text}” is not said word for word, so it is "
                        "on-screen text, not a caption"
                    )
        else:
            assert proposal.first_shot is not None
            source, start, end = parse_shot(proposal.first_shot)
            if source not in {s.id for s in manifest.sources}:
                raise ValidationError(f"--first-shot {proposal.first_shot}: no source {source!r}")
            transcript_file = ws.transcript_for(source)
            transcript = (
                load_artifact(Transcript, transcript_file) if transcript_file.is_file() else None
            )
            variant_edl, warnings = first_shot_edl(
                edl, source, start, end, transcript, proposal.name
            )
            new_first = variant_edl.ranges[0]
            variant_plan = shift_plan(
                plan, old_first=first.output_duration, new_first=new_first.output_duration
            )
            if caption_path is not None:
                heard = _transcripts(ws, variant_edl)
                if not heard:
                    raise ValidationError(
                        "the variant needs captions but no transcript of its audio was found"
                    )
                _, captions = stage_captions(heard, variant_edl, ws, brand, persist_edl=False)
                own_captions = str(captions.with_suffix(".json"))
            folder = ws.analysis / "variants" / proposal.name
            own_edl = str(save_artifact(variant_edl, folder / "edl.json"))
            own_plan = str(save_artifact(variant_plan, folder / "motion-plan.json"))
            changes.append(
                VariantChange(element="first range", before=_range(first), after=_range(new_first))
            )
            delta = new_first.output_duration - first.output_duration
            shared += [f"ranges 2-{len(edl.ranges)}" if len(edl.ranges) > 1 else "no other range"]
            shared.append(f"motion after the first range, moved by {delta:+.2f}s")

        render_edl, render_plan = variant_edl, variant_plan
        if request.seconds is not None:
            render_edl, head_plan = head_of(variant_edl, variant_plan, request.seconds)
            render_plan = head_plan or variant_plan
        suffix = f"-{request.seconds:g}s" if request.seconds is not None else ""
        output = ws.previews / f"opening-{proposal.name}{suffix}.mp4"
        stage_render(
            render_edl, manifest, ws, quality=request.quality, captions=captions, output=output,
            renderer=Renderer.REMOTION, motion_plan=render_plan,
            remotion_license_attestation=state.remotion_license_attestation,
            persist_artifacts=False, base_name=f"variants/{proposal.name}/base-{request.quality}",
        )  # fmt: skip
        made.append(
            OpeningVariant(
                name=proposal.name, hypothesis=hypothesis, text=proposal.text,
                first_shot=proposal.first_shot, shown_as=shown_as, changes=changes,
                shared=shared, warnings=warnings,
                preview=str(output) if request.seconds is not None else "",
                preview_seconds=request.seconds,
                full="" if request.seconds is not None else str(output),
                audio_sha256=audio_sha256(output), edl=own_edl, motion_plan=own_plan,
                captions=own_captions,
            )
        )  # fmt: skip

    if axis is VariantAxis.TEXT:
        heard = {v.audio_sha256 for v in made if v.audio_sha256}
        if len(heard) > 1:
            raise ValidationError(
                "the text variants do not share the same audio; a text-only change must "
                "leave the sound untouched"
            )
        for variant in made:
            if variant.audio_sha256:
                variant.shared = [
                    "audio (identical, checked by hash)" if s == "audio" else s
                    for s in variant.shared
                ]

    if request.only and known is not None:
        merged = []
        for old in known.variants:
            new = next((m for m in made if m.name == old.name), None)
            if new is None:
                merged.append(old)
                continue
            merged.append(
                old.model_copy(
                    update={
                        "full": new.full or old.full,
                        "preview": new.preview or old.preview,
                        "audio_sha256": new.audio_sha256,
                        "edl": new.edl or old.edl,
                        "motion_plan": new.motion_plan or old.motion_plan,
                        "captions": new.captions or old.captions,
                    }
                )
            )
        chosen = request.only[0] if request.seconds is None and len(request.only) == 1 else None
        result = known.model_copy(
            update={"variants": merged, "chosen": chosen or known.chosen, "base": base}
        )
    else:
        result = OpeningVariantSet(axis=axis, base=base, variants=made)
    save_artifact(result, registry)
    return result, notes


def _range(rng) -> str:
    quote = f" “{rng.quote}”" if rng.quote else ""
    return f"{rng.source} {rng.start:.2f}-{rng.end:.2f}s{quote}"
