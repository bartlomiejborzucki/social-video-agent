"""Contract-based brand QA using renderer evidence, not heuristic context."""

from __future__ import annotations

from pathlib import Path

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
