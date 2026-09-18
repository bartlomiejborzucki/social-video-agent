"""Contract-based brand QA using renderer evidence, not heuristic context."""

from __future__ import annotations

from pathlib import Path

from social_video.captions.features import ACTIVE_WORD_HIGHLIGHT, ACTIVE_WORD_UNAVAILABLE
from social_video.ffmpeg.probe import probe
from social_video.schemas.config import BrandContract
from social_video.schemas.qa import QACheck, QAReport, QASeverity, RenderManifest


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
