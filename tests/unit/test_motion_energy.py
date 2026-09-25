"""1.2/1.3 motion: energy levels, accents, beats, sound, hook variants."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError as PydanticValidationError

from social_video.analysis.beats import onsets, snap
from social_video.captions.features import (
    CAPTION_ANIMATION,
    CAPTION_ANIMATION_UNAVAILABLE,
    caption_features,
)
from social_video.errors import ValidationError
from social_video.motion.energy import ENERGY, energy_preset
from social_video.motion.review import review_moments, with_hook
from social_video.motion.sfx import sync_sfx
from social_video.motion.suggest import accept_accents, find_accents
from social_video.pipeline import _check_movement
from social_video.project_config import compile_brand_contract
from social_video.schemas.brand import BrandProfile, CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.config import BrandContract
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import (
    AccentKind,
    MotionElement,
    MotionPlan,
    Transition,
)
from social_video.schemas.transcript import Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing
from social_video.workspace.layout import Workspace


def _config(tmp_path: Path, extra: str = "") -> Path:
    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True)
    (project / "assets" / "Lato.ttf").write_bytes(b"fixture-font")
    config = project / "social-video.yaml"
    config.write_text(f"schema_version: 1\nfont_file: assets/Lato.ttf\n{extra}", encoding="utf-8")
    return config


def _brand(tmp_path: Path, extra: str = "") -> BrandProfile:
    config = _config(tmp_path, extra)
    return compile_brand_contract(
        config, Workspace.at(config.parent / "edit"), project_root=config.parent
    ).brand


def test_calm_is_the_old_behaviour_exactly(tmp_path: Path) -> None:
    brand = _brand(tmp_path, "punch_in_intensity: 0.1\n")

    assert brand.motion_energy == "calm"
    assert brand.punch_in_max == 1.12
    assert brand.motion_intensity == 0.1
    assert brand.captions.animation == "none"


def test_a_livelier_energy_moves_more_and_animates_words(tmp_path: Path) -> None:
    brand = _brand(tmp_path, "motion_energy: bold\nstyle_pack: bold-social\n")

    assert brand.punch_in_max == ENERGY["bold"].punch_in_max
    assert brand.motion_intensity == ENERGY["bold"].motion_intensity
    assert brand.captions.animation == "box"
    assert brand.style_pack == "bold-social"


def test_a_still_project_stays_still_at_any_energy(tmp_path: Path) -> None:
    assert _brand(tmp_path, "motion_energy: bold\npunch_in_intensity: 0\n").motion_intensity == 0


def test_an_explicit_caption_animation_wins(tmp_path: Path) -> None:
    brand = _brand(tmp_path, "motion_energy: bold\ncaption_style:\n  animation: pop\n")

    assert brand.captions.animation == "pop"


def _element(kind: str, **fields) -> MotionElement:
    return MotionElement(type=kind, start=0, end=2, reason="r", **fields)


def test_the_new_graphics_say_what_they_need() -> None:
    _element("hook_card", text="Trzy błędy")
    _element("chart", items=["2024: 38", "2025: 71,5%"])
    _element("compare", items=["Przed: 3 h", "Po: 20 min"])
    _element("steps", items=["Nagraj", "Wytnij"])
    with pytest.raises(PydanticValidationError, match=r"first 0\.5 s"):
        MotionElement(type="hook_card", start=1, end=2, text="late", reason="r")
    with pytest.raises(PydanticValidationError, match="at most 90"):
        _element("hook_card", text="x" * 91)
    with pytest.raises(PydanticValidationError, match="Label: number"):
        _element("chart", items=["2024: dużo", "2025: 71"])
    with pytest.raises(PydanticValidationError, match="needs 2 items"):
        _element("compare", items=["Przed: 3 h"])


def _contract(energy: str) -> BrandContract:
    preset = energy_preset(energy)
    return BrandContract(
        project_config_path="c.yaml",
        project_config_sha256="0" * 64,
        project_root=".",
        brand=BrandProfile(
            punch_in_max=preset.punch_in_max,
            motion_intensity=preset.motion_intensity,
            motion_energy=energy,
        ),
        output_width=1080,
        output_height=1920,
        output_fps="30/1",
    )


def test_transitions_are_held_to_the_energy_budget() -> None:
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=30)])
    plan = MotionPlan(
        rationale="r",
        transitions=[Transition(at=5.0 * n, reason="cut") for n in range(1, 4)],
    )

    _check_movement(edl, plan, _contract("bold"))  # 8/min over 30 s allows 4
    with pytest.raises(ValidationError, match="motion_energy allows 2"):
        _check_movement(edl, plan, _contract("lively"))
    with pytest.raises(ValidationError, match="allows 0"):
        _check_movement(edl, plan, _contract("calm"))


def _transcript(words: list[tuple[str, float, float]], duration: float) -> Transcript:
    tokens = [TranscriptToken(text=t, start=s, end=e) for t, s, e in words]
    return Transcript(
        source_id="clip",
        source_fingerprint="f" * 16,
        duration=duration,
        provider="test",
        tokens=synthesize_spacing(tokens),
    )


SPEECH = [
    ("Trzy", 0.0, 0.3), ("błędy", 0.35, 0.7), ("zabijają", 0.75, 1.2), ("zasięgi.", 1.25, 1.8),
    ("Aż", 3.0, 3.2), ("73", 3.25, 3.5), ("procent", 3.55, 3.9), ("ogląda", 3.95, 4.3),
    ("bez", 4.35, 4.5), ("dźwięku.", 4.55, 5.0),
    ("Po", 7.0, 7.1), ("pierwsze", 7.15, 7.5), ("napisy,", 7.55, 7.9), ("po", 8.0, 8.1),
    ("drugie", 8.15, 8.5), ("hook.", 8.55, 8.9),
    ("Ale", 11.0, 11.2), ("to", 11.25, 11.3), ("nie", 11.35, 11.5), ("wszystko.", 11.55, 12.0),
    ("Dlaczego", 14.0, 14.4), ("tak", 14.45, 14.6), ("jest?", 14.65, 15.0),
    ("Bo", 16.8, 17.0), ("działa.", 17.05, 17.6),
]  # fmt: skip


def _found(energy: str = "bold", beats=None):
    transcript = _transcript(SPEECH, 24.0)
    edl = EDL(
        ranges=[
            EDLRange(source="clip", start=0, end=9.5),
            # A jump in the source: a place a transition reads as deliberate.
            EDLRange(source="clip", start=10.8, end=24.0),
        ]
    )
    return find_accents(transcript, edl, energy_preset(energy), beats=beats)


def test_accents_are_found_where_the_speech_puts_them() -> None:
    found = _found("bold")
    by_kind = {c.kind: c for c in found.candidates}

    hook = by_kind[AccentKind.HOOK].element
    assert hook is not None and hook.type.value == "hook_card"
    assert hook.text == "Trzy błędy zabijają zasięgi"
    stat = by_kind[AccentKind.STAT].element
    assert stat is not None and stat.text == "73%"
    assert stat.secondary_text == "ogląda bez dźwięku."
    steps = by_kind[AccentKind.STEPS].element
    assert steps is not None and steps.items == ["napisy", "hook"]
    assert by_kind[AccentKind.QUESTION].element.text == "Dlaczego tak jest?"
    assert by_kind[AccentKind.PUNCHLINE].punch_in.scale == ENERGY["bold"].punch_in_max
    transition = by_kind[AccentKind.TRANSITION].transition
    assert transition is not None and transition.at == pytest.approx(9.5)
    assert [c.id for c in found.candidates] == [
        f"acc-{n:03d}" for n in range(1, len(found.candidates) + 1)
    ]


def test_calm_proposes_fewer_accents_and_no_transitions() -> None:
    calm, bold = _found("calm"), _found("bold")

    assert len(calm.candidates) < len(bold.candidates)
    assert all(c.transition is None for c in calm.candidates)
    gaps = [b.at - a.at for a, b in zip(calm.candidates, calm.candidates[1:], strict=False)]
    assert all(gap >= ENERGY["calm"].min_accent_gap for gap in gaps)


def test_punch_ins_move_onto_a_nearby_beat() -> None:
    plain = {c.kind: c for c in _found("bold").candidates}[AccentKind.PUNCHLINE]
    beat = round(plain.punch_in.start + 0.08, 3)

    snapped = {c.kind: c for c in _found("bold", beats=[beat]).candidates}[AccentKind.PUNCHLINE]

    assert snapped.punch_in.start == beat


def test_accepting_builds_the_motion_plan_and_refuses_overlaps() -> None:
    found = _found("bold")
    ids = [c.id for c in found.candidates]

    plan, skipped = accept_accents(None, found, ids)
    again, _ = accept_accents(plan, found, ids)

    assert plan.elements and plan.transitions and plan.punch_ins
    assert again.model_dump() == plan.model_dump()
    assert skipped == [] or all("overlaps" in line for line in skipped)
    with pytest.raises(ValidationError, match="unknown accent 'acc-999'"):
        accept_accents(plan, found, ["acc-999"])


def test_onsets_find_clicks_in_a_signal() -> None:
    rate = 11025
    signal = np.zeros(rate * 3, dtype=np.float32)
    for at in (0.5, 1.25, 2.0, 2.5):
        start = int(at * rate)
        signal[start : start + 200] = np.hanning(200) * 0.9

    beats = onsets(signal, rate)

    for expected in (0.5, 1.25, 2.0, 2.5):
        assert any(abs(beat - expected) < 0.05 for beat in beats), (expected, beats)
    assert snap(1.3, beats) == pytest.approx(min(beats, key=lambda b: abs(b - 1.25)))
    assert snap(1.6, beats) == 1.6


def test_sound_lands_under_each_transition_and_graphic(tmp_path: Path) -> None:
    library = tmp_path / "sfx"
    library.mkdir()
    for name in ("whoosh-1.wav", "pop.wav", "hit.wav", "readme.txt"):
        (library / name).write_bytes(b"x")
    plan = MotionPlan(
        rationale="r",
        elements=[
            MotionElement(type="hook_card", start=0, end=1.5, text="Hook", reason="r"),
            MotionElement(type="stat", start=3, end=5, text="73%", reason="r"),
        ],
        transitions=[Transition(at=9.5, reason="cut")],
    )
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=12)])

    updated, added = sync_sfx(edl, plan, library)

    placed = {(Path(e.path).name, e.at) for e in added}
    assert placed == {("hit.wav", 0.0), ("pop.wav", 3.0), ("whoosh-1.wav", 9.3)}
    assert all(e.license_confirmed and e.gain_db == -10.0 for e in updated.sound_effects)
    _, again = sync_sfx(updated, plan, library)
    assert again == []


def test_a_hook_variant_replaces_or_adds_the_hook_card() -> None:
    plan = MotionPlan(rationale="r", elements=[_element("stat", text="73%")])

    added = with_hook(plan, "Nowy hook")
    replaced = with_hook(added, "Inny hook")

    assert [e.type.value for e in added.elements] == ["hook_card", "stat"]
    assert replaced.elements[0].text == "Inny hook"
    assert len(replaced.elements) == 2
    labels = [label for _, label in review_moments(replaced)]
    assert labels == ["hook_card", "stat"]


def test_word_animation_is_recorded_as_drawn_or_unavailable() -> None:
    track = CaptionTrack(
        cues=[
            CaptionCue(
                index=1, start=0, end=1, text="hej",
                words=[CaptionWord(text="hej", start=0, end=1)],
            )
        ]
    )  # fmt: skip
    style = CaptionStyle(highlight_active_word=True, animation="pop")

    assert CAPTION_ANIMATION in caption_features(style, track, highlight=True, animated=True)
    assert CAPTION_ANIMATION_UNAVAILABLE in caption_features(style, track, highlight=True)


def test_the_cli_suggests_accepts_and_adds_sound(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from social_video.cli import app
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.edl import EDL as EDLModel

    transcript = _transcript(SPEECH, 24.0)
    monkeypatch.setattr("social_video.pipeline.stage_transcribe", lambda *a, **k: transcript)
    workspace = Workspace.at(tmp_path / "edit")
    workspace.ensure()
    save_artifact(
        EDL(
            ranges=[
                EDLRange(source="clip", start=0, end=9.5),
                EDLRange(source="clip", start=10.8, end=24.0),
            ]
        ),
        workspace.edl,
    )
    library = tmp_path / "sfx"
    library.mkdir()
    (library / "whoosh.wav").write_bytes(b"x")
    (library / "pop.wav").write_bytes(b"x")
    runner = CliRunner()
    ws = str(workspace.root)

    found = runner.invoke(app, ["motion", "suggest", "clip.mp4", "-w", ws, "--energy", "bold"])
    accepted = runner.invoke(
        app, ["motion", "accept", "-w", ws, "--kind", "stat", "--kind", "transition"]
    )
    refused = runner.invoke(app, ["motion", "sfx", str(library), "-w", ws])
    sound = runner.invoke(app, ["motion", "sfx", str(library), "-w", ws, "--licensed"])

    assert found.exit_code == 0, found.output
    assert accepted.exit_code == 0, accepted.output
    plan = load_artifact(MotionPlan, workspace.motion_plan)
    assert [e.type.value for e in plan.elements] == ["stat"]
    assert len(plan.transitions) == 1
    assert refused.exit_code == 1 and "--licensed" in refused.output
    assert sound.exit_code == 0, sound.output
    assert len(load_artifact(EDLModel, workspace.edl).sound_effects) == 2
