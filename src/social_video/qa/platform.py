"""Does this output survive the feed it is going into?

Every platform paints its own UI over the video: a caption block and handle at
the bottom, action buttons down the right, a title row at the top. Type placed
under that furniture is simply not read. The numbers come from editable JSON
platform specs and are conservative estimates, so these are warnings that name
the measurement rather than errors that pretend to be authoritative.
"""

from __future__ import annotations

from social_video.schemas.brand import CaptionPosition
from social_video.schemas.config import BrandContract
from social_video.schemas.platform import PlatformSpec
from social_video.schemas.qa import QACheck, QASeverity

#: Caption positions that sit against the bottom edge, where the UI lives.
_BOTTOM_POSITIONS = {
    CaptionPosition.BOTTOM,
    CaptionPosition.LOWER_THIRD,
    CaptionPosition.LOWER_SAFE_ZONE,
}


def platform_checks(
    spec: PlatformSpec,
    *,
    duration: float,
    width: int | None,
    height: int | None,
    contract: BrandContract | None = None,
) -> list[QACheck]:
    """Checks for one destination, appended to an existing QA report."""
    checks = [_duration_check(spec, duration), _pacing_check(spec, duration)]
    if width and height:
        checks.append(_aspect_check(spec, width, height))
    if contract is not None:
        checks.extend(_layout_checks(spec, contract))
    return checks


def _duration_check(spec: PlatformSpec, duration: float) -> QACheck:
    too_long = duration > spec.max_duration
    too_short = duration < spec.min_duration
    if too_long:
        message = f"{duration:.1f}s exceeds the {spec.name} limit of {spec.max_duration:.0f}s"
    elif too_short:
        message = f"{duration:.1f}s is below the {spec.name} minimum of {spec.min_duration:.0f}s"
    else:
        message = f"{duration:.1f}s fits {spec.name}"
    return QACheck(
        name=f"{spec.name} duration limit",
        severity=QASeverity.ERROR if (too_long or too_short) else QASeverity.INFO,
        passed=not (too_long or too_short),
        message=message,
        measured=duration,
        expected=spec.max_duration,
    )


def _pacing_check(spec: PlatformSpec, duration: float) -> QACheck:
    over = duration > spec.recommended_max_duration
    return QACheck(
        name=f"{spec.name} recommended length",
        severity=QASeverity.WARNING if over else QASeverity.INFO,
        passed=not over,
        message=(
            f"{duration:.1f}s is within the {spec.recommended_max_duration:.0f}s editorial ceiling"
            if not over
            else f"{duration:.1f}s is past the {spec.recommended_max_duration:.0f}s "
            "editorial ceiling; the payoff has to justify it"
        ),
        measured=duration,
        expected=spec.recommended_max_duration,
    )


def _aspect_check(spec: PlatformSpec, width: int, height: int) -> QACheck:
    actual = width / height
    expected = [_ratio(value) for value in spec.aspect_ratios]
    matched = any(abs(actual - value) < 0.01 for value in expected if value is not None)
    return QACheck(
        name=f"{spec.name} aspect ratio",
        severity=QASeverity.WARNING,
        passed=matched,
        message=(
            f"{width}x{height} matches {', '.join(spec.aspect_ratios)}"
            if matched
            else f"{width}x{height} is not {', '.join(spec.aspect_ratios)}; "
            f"{spec.name} will letterbox or crop it"
        ),
        measured=round(actual, 4),
    )


def _layout_checks(spec: PlatformSpec, contract: BrandContract) -> list[QACheck]:
    checks: list[QACheck] = []
    style = contract.brand.captions
    if style.position in _BOTTOM_POSITIONS:
        clear = style.margin_pct >= spec.reserved_bottom_pct
        checks.append(
            QACheck(
                name=f"captions clear the {spec.name} interface",
                severity=QASeverity.WARNING,
                passed=clear,
                message=(
                    f"caption margin {style.margin_pct:.0f}% clears the estimated "
                    f"{spec.reserved_bottom_pct:.0f}% overlay"
                    if clear
                    else f"caption margin {style.margin_pct:.0f}% sits inside the estimated "
                    f"{spec.reserved_bottom_pct:.0f}% {spec.name} overlay; raise "
                    "bottom_margin_pct or the captions are covered"
                ),
                measured=style.margin_pct,
                expected=spec.reserved_bottom_pct,
            )
        )
    margins = contract.safe_margins or {}
    for edge, reserved in (
        ("bottom", spec.reserved_bottom_pct),
        ("right", spec.reserved_right_pct),
        ("top", spec.reserved_top_pct),
    ):
        # Graphics only need to clear the furniture on the edge they touch, and
        # the logo is the element that actually uses the top-right corner.
        if edge != "bottom" and contract.brand.logo_usage == "none":
            continue
        value = float(margins.get(edge, 0.0))
        clear = value >= reserved
        checks.append(
            QACheck(
                name=f"graphics clear the {spec.name} {edge} interface",
                severity=QASeverity.WARNING,
                passed=clear,
                message=(
                    f"{edge} safe margin {value:.0f}% clears the estimated {reserved:.0f}%"
                    if clear
                    else f"{edge} safe margin {value:.0f}% is inside the estimated "
                    f"{reserved:.0f}% {spec.name} overlay"
                ),
                measured=value,
                expected=reserved,
            )
        )
    return checks


def _ratio(value: str) -> float | None:
    try:
        width, height = value.split(":", 1)
        return int(width) / int(height)
    except (ValueError, ZeroDivisionError):
        return None
