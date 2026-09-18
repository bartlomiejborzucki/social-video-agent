"""Platform safe zones, duration limits, and publishing metadata."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from social_video.errors import ValidationError
from social_video.profiles import available_platforms, load_platform
from social_video.qa.platform import platform_checks
from social_video.schemas.brand import BrandProfile, CaptionPosition, CaptionStyle
from social_video.schemas.config import BrandContract
from social_video.schemas.publish import PublishMetadata


def _contract(**caption_kwargs) -> BrandContract:
    return BrandContract(
        project_config_path="config.yaml",
        project_config_sha256="a" * 64,
        project_root="/project",
        brand=BrandProfile(captions=CaptionStyle(**caption_kwargs)),
        output_width=1080,
        output_height=1920,
        output_fps="30/1",
        safe_margins={"top": 6, "right": 6, "bottom": 12, "left": 6},
    )


def _named(checks, name: str):
    return next(check for check in checks if check.name == name)


def test_every_shipped_platform_loads() -> None:
    assert set(available_platforms()) >= {"reels", "shorts", "tiktok"}
    for name in available_platforms():
        assert load_platform(name).reserved_bottom_pct > 0


def test_a_clip_past_the_hard_limit_is_an_error_not_a_warning() -> None:
    checks = platform_checks(load_platform("shorts"), duration=200.0, width=1080, height=1920)
    limit = _named(checks, "shorts duration limit")
    assert not limit.passed and limit.severity.value == "error"


def test_a_clip_under_the_platform_minimum_is_an_error() -> None:
    checks = platform_checks(load_platform("reels"), duration=2.0, width=1080, height=1920)
    limit = _named(checks, "reels duration limit")
    assert not limit.passed and limit.severity.value == "error"
    assert "minimum" in limit.message


def test_a_clip_past_the_editorial_ceiling_only_warns() -> None:
    checks = platform_checks(load_platform("reels"), duration=120.0, width=1080, height=1920)
    assert _named(checks, "reels duration limit").passed
    ceiling = _named(checks, "reels recommended length")
    assert not ceiling.passed and ceiling.severity.value == "warning"


def test_a_landscape_output_is_flagged_for_a_vertical_feed() -> None:
    checks = platform_checks(load_platform("tiktok"), duration=30.0, width=1920, height=1080)
    assert not _named(checks, "tiktok aspect ratio").passed


def test_captions_inside_the_feed_overlay_are_reported_with_both_numbers() -> None:
    contract = _contract(margin_pct=12.0, position=CaptionPosition.LOWER_SAFE_ZONE)
    checks = platform_checks(
        load_platform("reels"), duration=30.0, width=1080, height=1920, contract=contract
    )
    covered = _named(checks, "captions clear the reels interface")
    assert not covered.passed
    assert "12%" in covered.message and "22%" in covered.message


def test_captions_above_the_overlay_pass() -> None:
    contract = _contract(margin_pct=24.0, position=CaptionPosition.LOWER_SAFE_ZONE)
    checks = platform_checks(
        load_platform("reels"), duration=30.0, width=1080, height=1920, contract=contract
    )
    assert _named(checks, "captions clear the reels interface").passed


def test_centred_captions_are_not_judged_against_the_bottom_overlay() -> None:
    contract = _contract(margin_pct=2.0, position=CaptionPosition.CENTER)
    checks = platform_checks(
        load_platform("reels"), duration=30.0, width=1080, height=1920, contract=contract
    )
    assert not any(check.name.startswith("captions clear") for check in checks)


def test_hashtags_are_normalised_and_deduplicated() -> None:
    metadata = PublishMetadata(
        platform="reels", language="pl", title="Tytuł", hashtags=["montaż", "#Reels"]
    )
    assert metadata.hashtags == ["#montaż", "#Reels"]
    with pytest.raises(PydanticValidationError, match="duplicate hashtag"):
        PublishMetadata(platform="reels", language="pl", title="T", hashtags=["ai", "#AI"])
    with pytest.raises(PydanticValidationError, match="single word"):
        PublishMetadata(platform="reels", language="pl", title="T", hashtags=["dwa słowa"])


def test_delivery_rejects_copy_the_platform_would_truncate() -> None:
    from social_video.delivery import _check_publish_limits

    spec = load_platform("shorts")
    long_title = PublishMetadata(platform="shorts", language="pl", title="x" * 120)
    with pytest.raises(ValidationError, match="shorts shows 100"):
        _check_publish_limits(long_title, [spec])
    _check_publish_limits(PublishMetadata(platform="shorts", language="pl", title="x" * 80), [spec])
