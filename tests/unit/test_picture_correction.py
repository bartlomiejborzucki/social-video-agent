"""Measured picture correction: decided from what a recording measures, inside ceilings."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from social_video.edl import picture
from social_video.edl.picture import (
    DENOISE_STRENGTH,
    MAX_CONTRAST,
    MAX_GAMMA,
    MAX_SHARPEN,
    NO_CORRECTION,
    PictureMeasurement,
    plan_correction,
    weak_source_notes,
)
from social_video.ffmpeg.probe import MediaInfo, VideoStream

#: A phone recording by a window: nothing here needs anything.
GOOD = PictureMeasurement(
    median=138.0,
    low=40.0,
    high=205.0,
    cast=0.02,
    enlargement=1.0,
    bits_per_pixel=0.16,
    frames=10,
)


def _measure(**changes) -> PictureMeasurement:
    return dataclasses.replace(GOOD, **changes)


def _applied(correction, source: str = "kamera") -> dict[str, dict]:
    return {step["name"]: step for step in correction.of(source).evidence()["applied"]}


def test_a_good_recording_is_left_exactly_as_recorded() -> None:
    plan = plan_correction({"kamera": GOOD})

    assert not plan.changed
    assert plan.of("kamera").pre == "" and plan.of("kamera").post_scale == ""
    assert plan.summary().startswith("picture left as recorded")
    assert {step["name"] for step in plan.of("kamera").evidence()["skipped"]} == {
        "denoise",
        "exposure",
        "contrast",
        "sharpen",
        "colour cast",
    }


def test_no_measurement_means_no_processing() -> None:
    assert not NO_CORRECTION.changed
    assert NO_CORRECTION.of("kamera").pre == ""
    assert NO_CORRECTION.evidence()["sources"] == {}


def test_a_dark_recording_is_lifted_toward_the_target_and_says_from_where() -> None:
    plan = plan_correction({"kamera": _measure(median=95.0, low=20.0, high=170.0)})

    exposure = _applied(plan)["exposure"]
    assert 1.04 < exposure["gamma"] < MAX_GAMMA
    assert "lifted from 95" in exposure["reason"]
    assert plan.of("kamera").pre.startswith("eq=gamma=")


def test_the_lift_stops_at_its_ceiling_however_dark_the_recording() -> None:
    plan = plan_correction({"kamera": _measure(median=40.0, low=5.0, high=120.0)})

    exposure = _applied(plan)["exposure"]
    assert exposure["gamma"] == MAX_GAMMA
    assert "at the ceiling" in exposure["reason"]


def test_a_dark_recording_is_lifted_toward_the_well_lit_ones_of_the_same_edit() -> None:
    alone = plan_correction({"wieczor": _measure(median=100.0)})
    beside = plan_correction({"wieczor": _measure(median=100.0), "okno": _measure(median=150.0)})

    assert _applied(beside, "wieczor")["exposure"]["target_luma"] == 140.0, "bounded"
    assert (
        _applied(beside, "wieczor")["exposure"]["gamma"]
        > _applied(alone, "wieczor")["exposure"]["gamma"]
    )
    assert not beside.of("okno").changed, "a well-lit recording is never darkened to match"


def test_a_lift_brings_back_the_contrast_it_costs() -> None:
    plan = plan_correction({"kamera": _measure(median=60.0, low=10.0, high=160.0)})

    contrast = _applied(plan)["contrast"]
    assert 1.02 <= contrast["contrast"] <= MAX_CONTRAST
    assert "gamma=" in plan.of("kamera").pre and "contrast=" in plan.of("kamera").pre
    assert plan.of("kamera").pre.count("eq=") == 1, "one eq filter carries both"


def test_a_flat_picture_gets_contrast_within_the_ceiling() -> None:
    plan = plan_correction({"kamera": _measure(low=110.0, high=160.0)})

    assert _applied(plan)["contrast"]["contrast"] == MAX_CONTRAST
    assert "flat picture" in _applied(plan)["contrast"]["reason"]
    assert "exposure" not in _applied(plan)


@pytest.mark.parametrize(
    ("enlargement", "expected"),
    [(1.0, None), (1.1, None), (1.5, 0.45), (2.3, 0.77), (4.0, MAX_SHARPEN)],
)
def test_sharpening_follows_how_much_the_edit_enlarges(enlargement, expected) -> None:
    plan = plan_correction({"kamera": _measure(enlargement=enlargement)})

    if expected is None:
        assert plan.of("kamera").post_scale == ""
        return
    assert _applied(plan)["sharpen"]["sharpen"] == pytest.approx(expected, abs=0.01)
    assert plan.of("kamera").post_scale == f"unsharp=5:5:{expected:.2f}:5:5:0.0"
    assert plan.of("kamera").pre == "", "sharpening runs after the scale, not before"


def test_only_a_heavily_compressed_recording_is_denoised_and_first() -> None:
    clean = plan_correction({"kamera": _measure(bits_per_pixel=0.09)})
    crushed = plan_correction({"kamera": _measure(bits_per_pixel=0.03, median=80.0)})
    unknown = plan_correction({"kamera": _measure(bits_per_pixel=None)})

    assert "denoise" not in _applied(clean) and "denoise" not in _applied(unknown)
    assert _applied(crushed)["denoise"]["denoise"] == DENOISE_STRENGTH
    assert crushed.of("kamera").pre.startswith("hqdn3d="), "before the lift raises its noise"


def test_a_colour_cast_is_reported_and_never_corrected() -> None:
    plan = plan_correction({"kamera": _measure(cast=0.15)})

    assert not plan.changed
    (cast,) = [s for s in plan.of("kamera").evidence()["skipped"] if s["name"] == "colour cast"]
    assert "warm" in cast["reason"] and "not corrected" in cast["reason"]


def test_a_filter_this_ffmpeg_lacks_is_recorded_not_silently_dropped() -> None:
    plan = plan_correction(
        {"kamera": _measure(median=70.0, enlargement=2.0)},
        unavailable=frozenset({"eq", "unsharp"}),
    )

    skipped = {s["name"]: s["reason"] for s in plan.of("kamera").evidence()["skipped"]}
    assert not plan.changed
    assert "no eq filter" in skipped["exposure"]
    assert "no unsharp" in skipped["sharpen"]


def test_the_evidence_carries_its_own_ceilings_and_every_measurement() -> None:
    evidence = plan_correction({"b": _measure(median=70.0), "a": GOOD}).evidence()

    assert evidence["changed"] is True
    assert list(evidence["sources"]) == ["a", "b"]
    assert evidence["limits"] == {
        "max_gamma": MAX_GAMMA,
        "max_contrast": MAX_CONTRAST,
        "max_sharpen": MAX_SHARPEN,
        "max_denoise": DENOISE_STRENGTH,
    }
    assert evidence["sources"]["b"]["measured"]["median_luma"] == 70.0
    assert evidence["sources"]["a"]["measured"]["frames_measured"] == 10


def _info(width: int, height: int, *, bit_rate: int | None, fps: str = "30/1") -> MediaInfo:
    video = VideoStream(
        index=0, codec="h264", width=width, height=height, rotation=0, frame_rate=fps,
        nominal_frame_rate=fps, pix_fmt="yuv420p", color_transfer="bt709", nb_frames=None,
        bit_rate=bit_rate,
    )  # fmt: skip
    return MediaInfo(Path("kamera.mp4"), 40.0, 4_000_000, "mov,mp4", video, ())


def test_a_small_heavily_compressed_recording_is_named_as_a_weak_source() -> None:
    notes = weak_source_notes(_info(480, 854, bit_rate=450_000))

    assert len(notes) == 2
    assert "enlarged at least 2.2x" in notes[0] and "original file" in notes[0]
    assert "heavily compressed" in notes[1]


def test_a_full_size_recording_gets_no_note() -> None:
    assert weak_source_notes(_info(1080, 1920, bit_rate=10_000_000)) == []
    assert weak_source_notes(_info(3840, 2160, bit_rate=45_000_000)) == []


def test_bits_per_pixel_falls_back_to_the_file_size() -> None:
    info = _info(1080, 1920, bit_rate=None)

    assert picture.bits_per_pixel(info) == pytest.approx(800_000 / (1080 * 1920 * 30), rel=1e-6)


def test_frames_are_sampled_across_every_span_the_edit_uses() -> None:
    times = picture._sample_times([(0.0, 2.0), (10.0, 13.0)])

    assert len(times) == picture.SAMPLES_PER_SOURCE
    assert all(0.0 <= t <= 2.0 or 10.0 <= t <= 13.0 for t in times)
    assert any(t < 2.0 for t in times) and any(t > 10.0 for t in times)
    assert picture._sample_times([(1.0, 1.0)]) == ()


def _brand_checks(policy: str, evidence: dict, monkeypatch, *, recorded: str | None = None):
    from social_video.qa.brand import check_brand
    from social_video.schemas.brand import BrandProfile
    from social_video.schemas.config import BrandContract
    from social_video.schemas.qa import RenderManifest

    contract = BrandContract(
        project_config_path="c.yaml",
        project_config_sha256="e" * 64,
        project_root="/p",
        brand=BrandProfile(),
        output_width=1080,
        output_height=1920,
        output_fps="30/1",
        audio_cleanup_policy="none",
        picture_policy=policy,
    )

    class Video:
        display_size = (1080, 1920)

    class Info:
        video = Video()

    monkeypatch.setattr("social_video.qa.brand.probe", lambda _: Info())
    report = check_brand(
        Path("final.mp4"),
        contract,
        RenderManifest(
            output="final.mp4",
            edl="main",
            rendered_at="2026-11-11T00:00:00Z",
            duration=10,
            width=1080,
            height=1920,
            frame_rate="30/1",
            crf=19,
            preset="medium",
            picture_policy=recorded or policy,
            picture_applied=evidence,
        ),
    )
    return {check.name: check for check in report.checks if "picture" in check.name}


def test_brand_qa_accepts_a_measured_correction_and_discloses_it(monkeypatch) -> None:
    evidence = plan_correction({"kamera": _measure(median=70.0, enlargement=2.0)}).evidence()

    checks = _brand_checks("measured", evidence, monkeypatch)

    assert checks["picture correction policy"].passed
    assert checks["picture correction was measured"].passed
    assert checks["picture not over-processed"].passed
    disclosed = checks["picture change is disclosed"]
    assert "picture was changed: kamera" in disclosed.message
    assert "--no-picture-correction" in disclosed.message


def test_brand_qa_rejects_a_correction_beyond_its_ceiling(monkeypatch) -> None:
    evidence = plan_correction({"kamera": _measure(median=70.0)}).evidence()
    evidence["sources"]["kamera"]["applied"][0]["gamma"] = MAX_GAMMA + 0.4

    checks = _brand_checks("measured", evidence, monkeypatch)

    assert not checks["picture not over-processed"].passed
    assert "gamma" in checks["picture not over-processed"].message


def test_brand_qa_rejects_a_correction_with_no_measurement_behind_it(monkeypatch) -> None:
    fabricated = {
        "changed": True,
        "sources": {
            "kamera": {
                "changed": True,
                "filters": "eq=gamma=1.2",
                "applied": [{"name": "exposure", "reason": "because", "gamma": 1.2}],
                "skipped": [],
                "measured": {},
            }
        },
        "limits": {},
    }

    checks = _brand_checks("measured", fabricated, monkeypatch)

    assert not checks["picture correction was measured"].passed


def test_brand_qa_accepts_a_render_asked_for_as_recorded(monkeypatch) -> None:
    checks = _brand_checks("measured", NO_CORRECTION.evidence(), monkeypatch, recorded="none")

    assert checks["picture correction policy"].passed
    assert "as recorded" in checks["picture correction policy"].message
    assert checks["picture left as recorded"].passed


def test_brand_qa_notices_when_the_policy_was_ignored(monkeypatch) -> None:
    evidence = plan_correction({"kamera": _measure(median=70.0)}).evidence()

    checks = _brand_checks("none", evidence, monkeypatch, recorded="measured")

    assert not checks["picture correction policy"].passed


def test_an_edit_names_the_recordings_it_enlarges(tmp_path: Path) -> None:
    from social_video.edl.picture import edit_source_notes
    from social_video.schemas.edl import EDL, EDLRange

    edl = EDL(
        ranges=[
            EDLRange(source="maly", start=0, end=4),
            EDLRange(source="duzy", start=0, end=2),
        ]
    )
    notes = edit_source_notes(
        edl, [_info(480, 854, bit_rate=450_000), _info(1080, 1920, bit_rate=9_000_000)]
    )

    assert list(notes) == ["maly"]
    assert "enlarged 2.2x in this edit" in notes["maly"][0]
    assert "heavily compressed" in notes["maly"][1]
