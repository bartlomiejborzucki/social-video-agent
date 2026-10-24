"""2.1 content-first openings: config, first caption, brief, card detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from social_video.captions.chunk import build_caption_track
from social_video.captions.fit import layout_captions
from social_video.cli import app
from social_video.delivery import validate_delivery_manifest
from social_video.editorial.brief import load_brief, opening_line, parse_brief_entry
from social_video.edl.timeline import Timeline
from social_video.errors import ValidationError
from social_video.motion.energy import energy_preset
from social_video.motion.suggest import find_accents
from social_video.project_config import compile_brand_contract
from social_video.qa.opening import (
    end_card_violations,
    refuse_card_openings,
    timeline_violations,
)
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.brief import Brief
from social_video.schemas.config import OpeningPolicy, ProjectVideoConfig
from social_video.schemas.delivery import DeliveryManifest
from social_video.schemas.edl import EDL, EDLRange, Overlay, OverlayKind
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan
from social_video.schemas.plan import EditPlan
from social_video.schemas.source import SourceEntry, SourceManifest
from social_video.schemas.transcript import Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing
from social_video.workspace.layout import Workspace

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "brief-2026-10-13.txt"


def _transcript(words: list[tuple[str, float, float]], duration: float = 12.0) -> Transcript:
    tokens = [TranscriptToken(text=t, start=s, end=e) for t, s, e in words]
    return Transcript(source_id="a", source_fingerprint="f" * 16, duration=duration,
                      provider="test", tokens=synthesize_spacing(tokens))  # fmt: skip


SPEECH = [
    ("Kiedy", 0.4, 0.7), ("widzisz", 0.75, 1.1), ("efekt", 1.15, 1.4), ("pozwolenia", 1.45, 2.0),
    ("dziecku", 2.05, 2.4), ("na", 2.45, 2.55), ("naukę.", 2.6, 3.1),
    ("Potem", 3.6, 3.9), ("mówię", 3.95, 4.3), ("dalej", 4.35, 4.6), ("o", 4.65, 4.7),
    ("zaufaniu", 4.75, 5.2), ("i", 5.25, 5.3), ("lustrze.", 5.35, 5.9),
]  # fmt: skip


def _track(style: CaptionStyle, opening_text: str | None = None, words=SPEECH):
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=12)])
    return build_caption_track(_transcript(words), Timeline(edl), style=style,
                               opening_text=opening_text)  # fmt: skip


# -- config -------------------------------------------------------------------


def test_absent_keys_mean_content_first_and_the_keys_compile(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True)
    (project / "assets" / "Lato.ttf").write_bytes(b"fixture-font")
    config = project / "social-video.yaml"
    config.write_text("schema_version: 1\nfont_file: assets/Lato.ttf\n", encoding="utf-8")

    contract = compile_brand_contract(config, Workspace.at(project / "edit"), project_root=project)

    assert contract.opening == OpeningPolicy()
    assert contract.opening.opening_policy == "content_first"
    assert contract.brand.captions.first_cue_full_sentence is True
    assert contract.brand.captions.first_cue_max_words == 8
    config.write_text(
        "schema_version: 1\nfont_file: assets/Lato.ttf\nfirst_cue_max_words: 6\n"
        "max_leading_silence_s: 0.2\n",
        encoding="utf-8",
    )
    tuned = compile_brand_contract(config, Workspace.at(project / "edit"), project_root=project)
    assert tuned.opening.first_cue_max_words == 6
    assert tuned.opening.max_leading_silence_s == 0.2


def test_a_cover_in_the_timeline_needs_the_free_policy() -> None:
    with pytest.raises(ValueError, match="cover_in_timeline: true contradicts"):
        ProjectVideoConfig(cover_in_timeline=True)
    assert ProjectVideoConfig(
        opening_policy="free", cover_in_timeline=True
    ).opening.cover_in_timeline


def test_config_init_writes_the_opening_keys(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["config", "init", str(tmp_path)])

    assert result.exit_code == 0, result.output
    written = next(tmp_path.rglob("*.yaml")).read_text(encoding="utf-8")
    for key in ("opening_policy: content_first", "cover_in_timeline: false",
                "first_cue_full_sentence: true", "first_cue_max_words: 8",
                "max_leading_silence_s: 0.3"):  # fmt: skip
        assert key in written


# -- the first caption ------------------------------------------------------------


def test_the_first_cue_starts_at_zero_with_the_whole_first_sentence() -> None:
    style = CaptionStyle(max_words_per_cue=4, max_chars_per_cue=24, first_cue_full_sentence=True)

    cues = _track(style).cues

    assert cues[0].start == 0.0
    assert cues[0].text == "Kiedy widzisz efekt pozwolenia dziecku na naukę."
    assert all(len(c.text.split()) <= 4 and len(c.text) <= 24 for c in cues[1:])
    assert cues[1].text.startswith("Potem")


def test_the_first_cue_stops_at_its_word_limit_and_legacy_is_unchanged() -> None:
    capped = _track(CaptionStyle(first_cue_full_sentence=True, first_cue_max_words=4)).cues
    legacy = _track(CaptionStyle(max_words_per_cue=4)).cues

    assert capped[0].text == "Kiedy widzisz efekt pozwolenia" and capped[0].start == 0.0
    assert legacy[0].start == pytest.approx(0.4)
    assert len(legacy[0].text.split()) <= 4


def test_an_unspoken_opening_line_is_shown_until_the_speech_begins() -> None:
    style = CaptionStyle(max_words_per_cue=4, first_cue_full_sentence=True)
    late = [(w, s + 2.0, e + 2.0) for w, s, e in SPEECH]

    shown = _track(style, "„Mamo, pobaw się ze mną!”", late).cues
    dropped = _track(style, "„Mamo, pobaw się ze mną!”").cues

    assert shown[0].text == "„Mamo, pobaw się ze mną!”"
    assert (shown[0].start, shown[0].end) == (0.0, pytest.approx(2.39))
    assert shown[0].words and shown[1].index == 2
    assert len(shown[1].text.split()) <= 4, "after the line, the normal cue limits apply"
    assert dropped[0].start == 0.0 and dropped[0].text.startswith("Kiedy")


def test_the_long_first_cue_is_exempt_from_the_length_limit_only() -> None:
    style = CaptionStyle(max_words_per_cue=4, max_chars_per_cue=24, first_cue_full_sentence=True,
                         font_size_pct=3.0)  # fmt: skip
    track = _track(style)

    layout = layout_captions(track.cues, style, width=1080, height=1920)

    assert layout.first_cue_exempt
    assert 1 not in layout.over_length_cues
    assert layout.evidence()["first_cue_exempt"] is True


# -- the brief ----------------------------------------------------------------------


def test_the_brief_text_becomes_first_line_labels_and_cover() -> None:
    brief = load_brief(FIXTURE)

    assert [r.start for r in brief.rows] == [0.0, 3.0, 9.0, 22.0]
    assert brief.first_line_off_screen and brief.first_cue_text == "„Mamo, pobaw się ze mną!”"
    assert [label.text for label in brief.labels] == [
        "Jak postawić teraz granicę?", "Częsty odruch", "Spróbuj tak",
        "Jasna decyzja + miejsce na emocje",
    ]  # fmt: skip
    assert (brief.cover_title, brief.cover_subtitle) == (
        "NIE POBAWIĘ SIĘ TERAZ", "Bez kar, czyli jak? / Granice w praktyce")  # fmt: skip
    assert "Pierwsza klatka = scena" in brief.montage


def test_a_spoken_first_line_is_its_first_sentence() -> None:
    brief = parse_brief_entry(
        {
            "tytul": "Zaufanie",
            "nagranie": "Dziecko myje lustro.",
            "scenariusz": [
                {
                    "czas": "0–3 s",  # noqa: RUF001 - the brief prints an en dash
                    "ujecie": "Dziecko myje lustro",
                    "co_mowisz": "„Kiedy widzisz efekt pozwolenia dziecku na naukę. To działa.”",
                    "napis": "Kiedy widzisz efekt",
                },
            ],
            "okladka": "ZAUFANIE",
        }
    )

    assert not brief.first_line_off_screen
    assert brief.first_cue_text == "Kiedy widzisz efekt pozwolenia dziecku na naukę."
    assert brief.title == "Zaufanie" and brief.cover_title == "ZAUFANIE"


def test_a_package_with_several_reels_needs_a_choice(tmp_path: Path) -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    scenario = text.split("Scenariusz")[1].split("Montaż")[0]
    entry = {"tytul": "Nie pobawię się teraz", "nagranie": "x", "scenariusz": scenario,
             "montaz": "y", "okladka": "NIE POBAWIĘ SIĘ TERAZ"}  # fmt: skip
    package = tmp_path / "pakiet_sm_2026-10.json"
    package.write_text(json.dumps({"rolki": [entry, {**entry, "tytul": "Inna"}]}), encoding="utf-8")

    with pytest.raises(ValidationError, match="choose one with --entry or --match"):
        load_brief(package)
    assert load_brief(package, entry=1).title == "Inna"
    assert load_brief(package, match="Nie pobawię").first_line_off_screen


def test_a_childs_line_is_text_only_unless_the_recording_carries_it(tmp_path: Path) -> None:
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    save_artifact(load_brief(FIXTURE), ws.brief)
    parent_only = _transcript([("No", 0.2, 0.4), ("teraz", 0.45, 0.8)])
    with_child = _transcript([("Mamo,", 0.1, 0.4), ("pobaw", 0.45, 0.7), ("się", 0.75, 0.9),
                              ("ze", 0.95, 1.0), ("mną!", 1.05, 1.3)])  # fmt: skip

    assert opening_line(ws, parent_only) == "„Mamo, pobaw się ze mną!”"
    assert opening_line(ws, with_child) is None


def test_the_cli_imports_the_brief_as_overrides_and_labels(tmp_path: Path) -> None:
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    save_artifact(EditPlan(goal="Rolka", user_overrides=["keep calm"]), ws.edit_plan)

    result = CliRunner().invoke(app, ["brief", "import", str(FIXTURE), "-w", str(ws.root),
                                      "--labels"])  # fmt: skip

    assert result.exit_code == 0, result.output
    assert load_artifact(Brief, ws.brief).cover_title == "NIE POBAWIĘ SIĘ TERAZ"
    overrides = load_artifact(EditPlan, ws.edit_plan).user_overrides
    assert overrides[0] == "keep calm"
    assert any("first caption from 0.0 s" in line for line in overrides)
    assert any("cover.jpg only" in line for line in overrides)
    labels = [e for e in load_artifact(MotionPlan, ws.motion_plan).elements]
    assert [e.type for e in labels] == [MotionElementType.LABEL] * 4


def test_a_label_is_short() -> None:
    with pytest.raises(ValueError, match="at most 80 characters"):
        MotionElement(type="label", start=0, end=2, text="x" * 81, reason="r")


# -- cards in the timeline ------------------------------------------------------------


def _edl(**fields) -> EDL:
    return EDL(ranges=[EDLRange(source="a", start=0, end=10)], **fields)


def test_a_cover_or_card_at_the_start_is_a_violation_and_a_label_is_not() -> None:
    cover = Overlay(file="okladka.png", start_in_output=0.0, duration=1.0)
    film = Overlay(file="film.mp4", kind=OverlayKind.MOTION_FILM, start_in_output=0.0, duration=1.8)
    broll = Overlay(file="broll.mp4", start_in_output=0.0, duration=1.0)
    plan = MotionPlan(
        rationale="r",
        elements=[
            MotionElement(
                type="hook_card", start=0.0, end=1.8, text="Krótkie spodenki?", reason="r"
            ),
            MotionElement(type="label", start=0.0, end=3.0, text="Spróbuj tak", reason="r"),
        ],
    )

    found = timeline_violations(_edl(overlays=[cover, film, broll]), plan)

    assert [v.where.split(" ")[0] for v in found] == ["overlay", "overlay", "hook_card"]
    assert "cover.jpg" in found[0].fix
    assert timeline_violations(_edl(), MotionPlan(rationale="r", elements=plan.elements[1:])) == []


def test_a_timeline_that_opens_on_a_still_is_a_violation() -> None:
    sources = SourceManifest(sources=[SourceEntry(
            id="a", path="/x/okladka.png", fingerprint="f" * 16, size_bytes=1, duration=5.0,
            width=1080, height=1920, frame_rate="30/1", video_codec="png",
        )])  # fmt: skip

    (found,) = timeline_violations(_edl(), None, sources=sources)

    assert "opens on a still image" in found.what


def test_an_end_card_belongs_at_the_end() -> None:
    plan = MotionPlan(
        rationale="r",
        elements=[MotionElement(type="end_card", start=4.0, end=6.0, text="Obserwuj", reason="r")],
    )
    at_end = MotionPlan(
        rationale="r",
        elements=[MotionElement(type="end_card", start=8.0, end=10.0, text="Obserwuj", reason="r")],
    )

    assert end_card_violations(_edl(), plan)
    assert end_card_violations(_edl(), at_end) == []


def test_a_content_first_render_refuses_a_card_opening() -> None:
    edl = _edl(overlays=[Overlay(file="okladka.png", start_in_output=0.0, duration=1.0)])

    with pytest.raises(ValidationError, match="must open on the scene"):
        refuse_card_openings(edl, None, OpeningPolicy())
    refuse_card_openings(edl, None, OpeningPolicy(opening_policy="free"))


def test_no_hook_card_is_proposed_under_content_first() -> None:
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=12)])

    plain = find_accents(_transcript(SPEECH), edl, energy_preset("lively"))
    first = find_accents(_transcript(SPEECH), edl, energy_preset("lively"), content_first=True)

    assert any(c.kind.value == "hook" for c in plain.candidates)
    assert not any(c.kind.value == "hook" for c in first.candidates)


# -- the manifest ----------------------------------------------------------------------


def test_old_manifests_load_and_a_not_ready_one_is_refused(tmp_path: Path) -> None:
    edl_path = tmp_path / "edl.json"
    edl_path.write_text("{}", encoding="utf-8")
    import hashlib

    digest = hashlib.sha256(edl_path.read_bytes()).hexdigest()
    old = DeliveryManifest.model_validate(
        {
            "workspace": "w",
            "destination": "d",
            "edl_path": str(edl_path),
            "edl_sha256_before": digest,
            "edl_sha256_after": digest,
        }
    )
    not_ready = old.model_copy(update={"opening_ready": False, "opening_issues": ["card"]})

    assert old.cover_path is None and old.opening_ready is None
    validate_delivery_manifest(old)
    with pytest.raises(ValidationError, match="not ready: card"):
        validate_delivery_manifest(not_ready)
    validate_delivery_manifest(not_ready, require_ready=False)
