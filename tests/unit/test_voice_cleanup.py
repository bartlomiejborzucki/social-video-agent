"""Voice cleanup repairs what a recording measures, and nothing else.

The thresholds under test were calibrated against synthetic fixtures with one
known defect each, and against the same material without it. These tests pin
the separation: a clean recording must come out untouched, and a defect must be
both detected and repaired with a bounded amount of processing.
"""

from __future__ import annotations

import pytest

from social_video.edl.voice import (
    DEESSER_MAX,
    MAX_COMPRESSION_RATIO,
    MAX_NOISE_REDUCTION_DB,
    NO_CLEANUP,
    VoiceMeasurement,
    plan_cleanup,
)

#: A well-recorded voice: quiet floor, no rumble, no hum, ordinary esses.
#: Measured from the calibration fixture, not invented.
CLEAN = VoiceMeasurement(
    speech_level_db=-38.1,
    noise_floor_db=-66.0,
    peak_db=-25.0,
    flat_factor=0.0,
    low_band_relative_db=-19.4,
    hum_50_relative_db=-22.7,
    hum_60_relative_db=-20.7,
    sibilance_relative_db=-16.6,
    loudness_range_lu=8.0,
    windows=60,
)


def _measure(**changes: object) -> VoiceMeasurement:
    from dataclasses import replace

    return replace(CLEAN, **changes)


def _applied(plan) -> dict[str, dict]:
    return {step["name"]: step for step in plan.evidence()["applied"]}


def test_a_clean_recording_is_left_exactly_as_recorded() -> None:
    plan = plan_cleanup(CLEAN)

    assert plan.filters == ()
    assert plan.chain is None
    assert not plan.changed
    assert plan.summary() == "audio left as recorded; nothing measured above its threshold"
    # Every step still reports what it measured, so "nothing applied" is a
    # finding rather than an absence.
    assert len(plan.evidence()["skipped"]) == 6


def test_no_measurement_means_no_processing() -> None:
    plan = plan_cleanup(None)

    assert plan is NO_CLEANUP
    assert plan.chain is None
    assert plan.evidence()["measured"] == {}


def test_rumble_is_high_passed_only_when_measured() -> None:
    plan = plan_cleanup(_measure(low_band_relative_db=-12.1))

    assert "highpass=f=80:poles=2" in plan.filters
    assert "rumble" in _applied(plan)
    # A voice with a low fundamental but no rumble must not be filtered.
    assert not plan_cleanup(_measure(low_band_relative_db=-20.4)).changed


def test_hum_is_notched_at_the_measured_fundamental() -> None:
    fifty = plan_cleanup(_measure(hum_50_relative_db=-13.1, low_band_relative_db=-16.3))
    sixty = plan_cleanup(_measure(hum_60_relative_db=-13.1, low_band_relative_db=-16.3))

    assert "equalizer=f=50:width_type=h:w=8:g=-15" in fifty.filters
    assert "equalizer=f=60:width_type=h:w=8:g=-15" in sixty.filters
    # Only the fundamental: notching the harmonics would thin the voice.
    assert not any("f=100" in item or "f=120" in item for item in fifty.filters)


def test_broadband_rumble_is_not_mistaken_for_hum() -> None:
    """A tone concentrates its energy; rumble spreads it. That is the test."""
    rumble = _measure(low_band_relative_db=-12.8, hum_50_relative_db=-16.3)

    plan = plan_cleanup(rumble)

    assert "rumble" in _applied(plan)
    assert "mains hum" not in _applied(plan)


def test_denoising_scales_with_the_measured_ratio_and_stops_at_the_ceiling() -> None:
    mild = plan_cleanup(_measure(noise_floor_db=-46.0, speech_level_db=-30.0))
    severe = plan_cleanup(_measure(noise_floor_db=-40.0, speech_level_db=-38.0))

    mild_nr = _applied(mild)["broadband noise"]["noise_reduction_db"]
    severe_nr = _applied(severe)["broadband noise"]["noise_reduction_db"]
    assert 4 <= mild_nr < severe_nr <= MAX_NOISE_REDUCTION_DB
    assert severe_nr == MAX_NOISE_REDUCTION_DB


def test_a_quiet_noise_floor_is_not_denoised_however_narrow_the_ratio() -> None:
    """Constant material is not noisy material; only an audible floor is."""
    plan = plan_cleanup(_measure(noise_floor_db=-70.0, speech_level_db=-60.0))

    assert "broadband noise" not in _applied(plan)


def test_hot_sibilance_is_de_essed_gently_and_hiss_is_not() -> None:
    sibilant = plan_cleanup(_measure(sibilance_relative_db=-2.0))
    hiss = plan_cleanup(_measure(sibilance_relative_db=-10.6))

    intensity = _applied(sibilant)["sibilance"]["intensity"]
    assert intensity <= DEESSER_MAX
    assert "sibilance" not in _applied(hiss)


def test_a_wide_loudness_range_is_compressed_within_the_ceiling() -> None:
    wide = plan_cleanup(_measure(loudness_range_lu=15.0))
    normal = plan_cleanup(_measure(loudness_range_lu=8.0))

    assert _applied(wide)["dynamics"]["ratio"] <= MAX_COMPRESSION_RATIO
    assert "dynamics" not in _applied(normal)
    assert "dynamics" not in _applied(plan_cleanup(_measure(loudness_range_lu=None)))


def test_clipping_is_reported_and_never_repaired() -> None:
    plan = plan_cleanup(_measure(peak_db=0.0))

    assert "clipping" not in _applied(plan)
    skipped = {step["name"]: step["reason"] for step in plan.evidence()["skipped"]}
    assert "will not invent the missing waveform" in skipped["clipping"]


def test_the_chain_is_ordered_so_each_filter_sees_clean_input() -> None:
    plan = plan_cleanup(
        _measure(
            low_band_relative_db=-10.0,
            hum_50_relative_db=-11.0,
            noise_floor_db=-44.0,
            speech_level_db=-34.0,
            sibilance_relative_db=-2.0,
            loudness_range_lu=15.0,
        )
    )

    chain = plan.chain or ""
    order = [
        chain.index(item) for item in ("highpass", "equalizer", "afftdn", "deesser", "acompressor")
    ]
    assert order == sorted(order), chain


def test_every_applied_step_says_what_it_measured() -> None:
    plan = plan_cleanup(_measure(low_band_relative_db=-10.0, loudness_range_lu=15.0))

    for step in plan.evidence()["applied"]:
        assert step["reason"] and step["filter"]
        assert any(character.isdigit() for character in step["reason"])
    assert "audio cleaned:" in plan.summary()


@pytest.mark.parametrize(
    "limit",
    ["max_noise_reduction_db", "max_compression_ratio", "max_deesser_intensity"],
)
def test_the_evidence_carries_its_own_ceilings(limit: str) -> None:
    """QA checks the repair against these, not against this module's intent."""
    assert limit in plan_cleanup(CLEAN).evidence()["limits"]


# --- brand QA checks the repair, not the intention --------------------------


def _brand_report(policy: str, evidence: dict, monkeypatch, *, recorded: str | None = None):
    from pathlib import Path

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
        audio_cleanup_policy=policy,
    )

    class Video:
        display_size = (1080, 1920)

    class Info:
        video = Video()

    monkeypatch.setattr("social_video.qa.brand.probe", lambda _: Info())
    return check_brand(
        Path("final.mp4"),
        contract,
        RenderManifest(
            output="final.mp4",
            edl="main",
            rendered_at="2026-09-21T00:00:00Z",
            duration=10,
            width=1080,
            height=1920,
            frame_rate="30/1",
            brand_contract_sha256=contract.project_config_sha256,
            audio_cleanup_policy=policy if recorded is None else recorded,
            audio_cleanup_applied=evidence,
        ),
    )


#: The audio checks, so a report built without caption evidence can be scoped
#: to what these tests are about.
AUDIO_CHECKS = {
    "audio cleanup policy",
    "audio left as recorded",
    "audio cleanup was measured",
    "voice not over-processed",
    "required audio cleanup ran",
    "source audio not clipped",
    "audio change is disclosed",
}


def _audio_errors(report) -> set[str]:
    return {check.name for check in report.errors} & AUDIO_CHECKS


def test_brand_qa_accepts_a_measured_repair_and_discloses_it(monkeypatch) -> None:
    plan = plan_cleanup(_measure(low_band_relative_db=-10.0))

    report = _brand_report("measured", plan.evidence(), monkeypatch)

    assert _audio_errors(report) == set()
    disclosure = next(c for c in report.checks if c.name == "audio change is disclosed")
    assert "audio was changed" in disclosure.message
    assert "--no-audio-cleanup" in disclosure.message


def test_brand_qa_rejects_processing_beyond_its_ceiling(monkeypatch) -> None:
    evidence = plan_cleanup(_measure(noise_floor_db=-44.0, speech_level_db=-34.0)).evidence()
    evidence["applied"][0]["noise_reduction_db"] = MAX_NOISE_REDUCTION_DB + 6

    report = _brand_report("measured", evidence, monkeypatch)

    assert "voice not over-processed" in _audio_errors(report)


def test_brand_qa_rejects_a_repair_with_no_measurement_behind_it(monkeypatch) -> None:
    fabricated = {
        "changed": True,
        "chain": "afftdn=nr=12",
        "applied": [{"name": "broadband noise", "reason": "because", "filter": "afftdn=nr=12"}],
        "skipped": [],
        "measured": {},
        "limits": {},
    }

    report = _brand_report("measured", fabricated, monkeypatch)

    assert "audio cleanup was measured" in _audio_errors(report)


def test_brand_qa_notices_when_a_policy_was_ignored(monkeypatch) -> None:
    report = _brand_report(
        "none",
        plan_cleanup(_measure(low_band_relative_db=-10.0)).evidence(),
        monkeypatch,
        recorded="measured",
    )

    assert "audio cleanup policy" in _audio_errors(report)


def test_brand_qa_accepts_a_render_asked_for_without_cleanup(monkeypatch) -> None:
    """`--no-audio-cleanup` against a `measured` contract is a legitimate ask."""
    report = _brand_report("measured", NO_CLEANUP.evidence(), monkeypatch, recorded="none")

    assert _audio_errors(report) == set()
    policy = next(c for c in report.checks if c.name == "audio cleanup policy")
    assert "asked for the audio as recorded" in policy.message


def test_brand_qa_warns_about_a_clipped_source(monkeypatch) -> None:
    report = _brand_report("measured", plan_cleanup(_measure(peak_db=0.0)).evidence(), monkeypatch)

    warned = {check.name for check in report.warnings}
    assert "source audio not clipped" in warned
