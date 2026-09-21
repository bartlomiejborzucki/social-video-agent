"""Contract-based brand QA using renderer evidence, not heuristic context."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from social_video.captions.features import ACTIVE_WORD_HIGHLIGHT, ACTIVE_WORD_UNAVAILABLE
from social_video.edl.voice import (
    DEESSER_MAX,
    MAX_COMPRESSION_RATIO,
    MAX_NOISE_REDUCTION_DB,
)
from social_video.ffmpeg.probe import probe
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.config import BrandContract
from social_video.schemas.qa import QACheck, QAReport, QASeverity, RenderManifest


class _Add(Protocol):
    """How every check is recorded, so helpers can take it as a parameter."""

    def __call__(self, name: str, ok: bool, message: str, *, warning: bool = False) -> None: ...


def check_brand(
    output: Path,
    contract: BrandContract,
    render: RenderManifest,
    *,
    accepted_deviations: set[str] | None = None,
) -> QAReport:
    accepted_deviations = accepted_deviations or set()
    report = QAReport(output=str(output), edl=render.edl)

    def add(name: str, ok: bool, message: str, *, warning: bool = False) -> None:
        check = QACheck(
            name=name,
            passed=ok,
            severity=(
                QASeverity.WARNING if warning else (QASeverity.INFO if ok else QASeverity.ERROR)
            ),
            message=message,
            accepted=not ok and name in accepted_deviations,
        )
        if check.accepted:
            check.severity = QASeverity.WARNING
        report.checks.append(check)

    style = contract.brand.captions
    evidence = render.caption_style
    add(
        "brand contract applied",
        render.brand_contract_sha256 == contract.project_config_sha256,
        f"render={render.brand_contract_sha256 or 'none'}, "
        f"expected={contract.project_config_sha256}",
    )
    comparisons = {
        "caption font": (evidence.get("font_family"), style.font_family),
        "caption text colour": (evidence.get("primary_colour"), style.primary_colour),
        "caption background colour": (evidence.get("background_colour"), style.background_colour),
        "caption outline colour": (evidence.get("outline_colour"), style.outline_colour),
        "caption position": (evidence.get("position"), style.position.value),
        "caption bottom margin": (evidence.get("margin_pct"), style.margin_pct),
        "caption max lines": (evidence.get("max_lines"), style.max_lines),
        "caption font size": (evidence.get("font_size_pct"), style.font_size_pct),
        "caption outline or shadow": (
            evidence.get("outline_or_shadow"),
            style.outline_or_shadow.value,
        ),
        "caption corner radius": (evidence.get("corner_radius"), style.corner_radius),
        "caption words per cue": (evidence.get("max_words_per_cue"), style.max_words_per_cue),
        "caption chars per cue": (evidence.get("max_chars_per_cue"), style.max_chars_per_cue),
    }
    for name, (actual, expected) in comparisons.items():
        add(name, actual == expected, f"render={actual!r}, expected={expected!r}")
    add(
        "brand safe margins",
        render.brand_safe_margins == contract.safe_margins,
        f"render={render.brand_safe_margins}, expected={contract.safe_margins}",
    )
    applied = set(render.caption_features)
    if render.captions_burned:
        # Everything above compares the contract with a copy of itself. These
        # compare it with what the renderer reported actually drawing.
        add(
            "caption renderer evidence",
            bool(render.caption_renderer and applied),
            f"renderer={render.caption_renderer or 'unrecorded'}, "
            f"features={sorted(applied) or 'none recorded'}",
            warning=True,
        )
        add(
            "caption active-word highlight",
            not style.highlight_active_word or ACTIVE_WORD_HIGHLIGHT in applied,
            (
                "not requested by the contract"
                if not style.highlight_active_word
                else "applied"
                if ACTIVE_WORD_HIGHLIGHT in applied
                else f"the contract requires an active-word highlight but "
                f"{render.caption_renderer or 'the renderer'} did not draw one"
                + (
                    "; the caption track has no word timings"
                    if ACTIVE_WORD_UNAVAILABLE in applied
                    else ""
                )
            ),
        )
        add(
            "caption weight",
            not style.bold or "bold" in applied,
            "bold applied" if "bold" in applied else "the contract asks for bold captions",
        )
        _check_caption_layout(add, style, render.caption_layout)
    bed = render.audio_bed_applied
    add(
        "music policy",
        (bool(bed) and contract.music_policy != "none")
        or (not bed and contract.music_policy != "required"),
        (
            f"bed at {bed.get('gain_db')} dB, ducked={bed.get('ducked')}"
            if bed
            else f"no music bed; policy is {contract.music_policy}"
        ),
    )
    if bed:
        # A bed this close to the voice competes with it rather than sitting under it.
        quiet_enough = float(bed.get("gain_db", 0.0)) <= -12.0
        add(
            "music sits under the voice",
            quiet_enough and bool(bed.get("ducked")),
            f"gain={bed.get('gain_db')} dB, ducked={bed.get('ducked')}; "
            "expected at most -12 dB and sidechain ducking",
            warning=True,
        )
    _check_audio_cleanup(add, contract, render)
    add(
        "sfx policy",
        (render.sound_effects_applied > 0 and contract.sfx_policy != "none")
        or (render.sound_effects_applied == 0 and contract.sfx_policy != "required"),
        f"{render.sound_effects_applied} effect(s); policy is {contract.sfx_policy}",
    )
    background_required = style.background_style.value != "none"
    add(
        "caption background present",
        not background_required
        or (render.captions_burned and evidence.get("background_style") != "none"),
        f"background_style={evidence.get('background_style', 'missing')}",
    )
    info = probe(output)
    dimensions = info.video.display_size if info.video else None
    add(
        "brand output resolution",
        dimensions == (contract.output_width, contract.output_height),
        f"render={dimensions}, expected={(contract.output_width, contract.output_height)}",
    )
    aspect_ok = False
    if dimensions is not None:
        aspect_ok = (
            abs(dimensions[0] / dimensions[1] - contract.output_width / contract.output_height)
            < 0.001
        )
    add("brand output aspect ratio", aspect_ok, f"render={dimensions}")
    logo_required = contract.brand.logo_usage == "required"
    add(
        "required logo applied",
        not logo_required or render.logo_applied,
        "logo applied" if render.logo_applied else "no logo evidence in render manifest",
    )
    return report


def _check_audio_cleanup(add: _Add, contract: BrandContract, render: RenderManifest) -> None:
    """Check the repair that happened against the project's policy and the ceilings.

    The failure this guards against is an "enhanced" voice: a chain that ran
    because it always runs, or ran harder than the material warranted. Both are
    visible in the evidence, so neither has to be taken on trust.
    """
    policy = contract.audio_cleanup_policy
    evidence = render.audio_cleanup_applied
    recorded = render.audio_cleanup_policy
    add(
        "audio cleanup policy",
        recorded == policy or (policy != "none" and recorded == "none"),
        f"render used {recorded!r}, contract says {policy!r}"
        + (
            "; this render was asked for the audio as recorded"
            if policy != "none" and recorded == "none"
            else ""
        ),
    )
    if recorded == "none":
        add(
            "audio left as recorded",
            not (evidence.get("applied") or []),
            "no voice cleanup was applied",
        )
        return
    applied = list(evidence.get("applied") or [])
    limits = dict(evidence.get("limits") or {})
    measured = dict(evidence.get("measured") or {})
    add(
        "audio cleanup was measured",
        bool(measured),
        f"measured {len(measured)} value(s) before deciding"
        if measured
        else "no measurement was recorded, so no repair can be justified",
    )
    # One explicit check per ceiling rather than a generic loop: there are
    # three of them and each has its own unit.
    over: list[str] = []
    for step in applied:
        reduction = step.get("noise_reduction_db")
        if reduction is not None and float(reduction) > float(
            limits.get("max_noise_reduction_db", MAX_NOISE_REDUCTION_DB)
        ):
            over.append(f"denoise {reduction} dB")
        ratio = step.get("ratio")
        if ratio is not None and float(ratio) > float(
            limits.get("max_compression_ratio", MAX_COMPRESSION_RATIO)
        ):
            over.append(f"compression {ratio}:1")
        intensity = step.get("intensity")
        if intensity is not None and float(intensity) > float(
            limits.get("max_deesser_intensity", DEESSER_MAX)
        ):
            over.append(f"de-esser {intensity}")
    add(
        "voice not over-processed",
        not over,
        "every applied step is inside its ceiling"
        if not over
        else f"beyond the ceiling: {', '.join(over)}; this is where cleanup stops being "
        "a repair and starts being a different voice",
    )
    if policy == "required":
        add(
            "required audio cleanup ran",
            bool(applied) or bool(measured),
            f"{len(applied)} step(s) applied after measurement"
            if applied
            else "nothing needed repair, which the measurement confirms"
            if measured
            else "the policy requires a measured repair and none is recorded",
        )
    clipped = bool(measured.get("clipped"))
    add(
        "source audio not clipped",
        not clipped,
        f"the recording peaks at {measured.get('peak_db')} dBFS; clipping is damage in the "
        "source and is reported rather than repaired"
        if clipped
        else f"peaks at {measured.get('peak_db')} dBFS",
        warning=True,
    )
    add(
        "audio change is disclosed",
        True,
        (
            "audio was changed: "
            + "; ".join(str(step.get("reason", step.get("name"))) for step in applied)
            + ". Undo with --no-audio-cleanup or audio_cleanup_policy: none."
            if applied
            else "audio was left as recorded; nothing measured above its threshold"
        ),
        warning=bool(applied),
    )


def _check_caption_layout(add: _Add, style: CaptionStyle, layout: dict) -> None:
    """Check the caption geometry that was drawn, not the one that was asked for.

    A caption that was shortened to fit is the defect this exists for: the
    renderer used to clamp overflow and append an ellipsis, which looks
    plausible in a contact sheet and is wrong in the transcript.
    """
    if not layout:
        # libass wraps internally and has no truncation mode, so there is
        # nothing measured to check. Say so rather than passing silently.
        add(
            "caption layout measured",
            True,
            "no measured layout recorded; this renderer cannot truncate captions",
            warning=True,
        )
        return
    truncated = list(layout.get("truncated_cues") or [])
    add(
        "captions are drawn in full",
        not truncated,
        "every cue's drawn lines reproduce its text word for word"
        if not truncated
        else f"cue(s) {truncated} lost text between the caption track and the frame; "
        "a subtitle is a transcript and must never be shortened to fit",
    )
    ellipsis = list(layout.get("ellipsis_cues") or [])
    add(
        "captions carry no added ellipsis",
        not ellipsis,
        "no cue gained an ellipsis it did not have"
        if not ellipsis
        else f"cue(s) {ellipsis} end in an ellipsis that is not in the transcript; the "
        "renderer shortened them instead of wrapping, shrinking or failing",
    )
    box = float(layout.get("text_box_width_px") or 0.0)
    widest = float(layout.get("max_line_width_px") or 0.0)
    add(
        "captions fit the caption box",
        box > 0 and widest <= box,
        f"widest line {widest:.0f} px, box {box:.0f} px",
    )
    longest = int(layout.get("max_chars_per_cue") or 0)
    over_length = list(layout.get("over_length_cues") or [])
    add(
        "caption cue length within the contract",
        not over_length,
        f"longest cue {longest} characters, contract allows {style.max_chars_per_cue}"
        + (
            ""
            if not over_length
            else f"; cue(s) {over_length} are longer and could have been split on a word "
            "boundary, so the caption track was not built from this contract"
        ),
    )
    requested = int(layout.get("requested_font_size_px") or 0)
    smallest = int(layout.get("min_font_size_px") or requested)
    shrunk = list(layout.get("shrunk_cues") or [])
    add(
        "caption size matches the contract",
        not shrunk,
        f"{len(shrunk)} cue(s) were reduced from {requested} px to {smallest} px to stay "
        f"inside {style.max_lines} line(s); lower caption_style.max_chars_per_cue or "
        "font_size_pct so every cue renders at the contracted size"
        if shrunk
        else f"every cue drawn at the contracted {requested} px",
        warning=True,
    )
    add(
        "caption layout measured",
        bool(layout.get("font_measured")),
        "wrapped against the project font's own metrics"
        if layout.get("font_measured")
        else "the font could not be measured, so line widths are estimated",
        warning=True,
    )
