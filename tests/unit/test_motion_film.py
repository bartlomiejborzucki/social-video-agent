"""1.4 Claude Motion segments: spec, import, removal, evidence and brand QA."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from social_video.cli import app
from social_video.errors import ValidationError
from social_video.motion.film import (
    build_film_spec,
    import_film,
    load_registry,
    palette_share,
    remove_film_segment,
    segment_evidence,
    write_film_spec,
)
from social_video.pipeline import sync_end_hold
from social_video.project_config import compile_brand_contract
from social_video.qa.brand import _check_film_segments
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.config import BrandContract
from social_video.schemas.edl import EDL, EDLRange, Overlay, OverlayKind
from social_video.schemas.motion import MotionElement, MotionPlan
from social_video.schemas.motion_film import FilmSpec
from social_video.schemas.qa import RenderManifest
from social_video.schemas.visuals import CapabilityState
from social_video.workflow.service import _pending_films
from social_video.workspace.layout import Workspace
from tests.conftest import ffmpeg, requires_ffmpeg

W, H = 540, 960


def _plan() -> MotionPlan:
    return MotionPlan(
        rationale="r",
        elements=[
            MotionElement(type="hook_card", start=0.0, end=1.8, text="Błąd, który kosztuje",
                          reason="Opening hook."),
            MotionElement(type="lower_third", start=1.0, end=3.0, text="Ola", reason="Who."),
            MotionElement(type="stat", start=3.0, end=4.5, text="73%", reason="Figure."),
            MotionElement(type="chapter", start=5.0, end=7.0, text="Część druga",
                          secondary_text="Dlaczego", reason="New part."),
        ],
    )  # fmt: skip


def _contract(tmp_path: Path, extra: str = "") -> BrandContract:
    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True, exist_ok=True)
    (project / "assets" / "Lato.ttf").write_bytes(b"fixture-font")
    (project / "assets" / "logo.png").write_bytes(b"fixture-logo")
    config = project / "social-video.yaml"
    config.write_text(
        "schema_version: 1\nfont: Lato\nfont_file: assets/Lato.ttf\nlogo_file: assets/logo.png\n"
        f'brand_colors: ["#E63946"]\ndefault_resolution: "{W}x{H}"\n'
        f"target_platforms: [reels]\n{extra}",
        encoding="utf-8",
    )
    return compile_brand_contract(config, Workspace.at(project / "edit"), project_root=project)


def _edl(**fields) -> EDL:
    return EDL(
        output_width=W, output_height=H, ranges=[EDLRange(source="a", start=0, end=10)], **fields
    )


def _workspace(tmp_path: Path, contract: BrandContract | None = None) -> Workspace:
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    save_artifact(_edl(output_fps="30"), ws.edl)
    save_artifact(_plan(), ws.motion_plan)
    if contract is not None:
        save_artifact(contract, ws.brand_contract)
    return ws


def _export(path: Path, parts: list[tuple[str, float]], size: tuple[int, int] = (W, H)) -> Path:
    args: list[str] = []
    for colour, seconds in parts:
        args += ["-f", "lavfi", "-i", f"color=c={colour}:s={size[0]}x{size[1]}:r=30:d={seconds}"]
    concat = "".join(f"[{i}:v]" for i in range(len(parts)))
    ffmpeg(
        *args, "-filter_complex", f"{concat}concat=n={len(parts)}:v=1:a=0[v]", "-map", "[v]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    )  # fmt: skip
    return path


# -- spec ---------------------------------------------------------------------


def test_the_spec_takes_full_frame_graphics_in_the_brands_terms(tmp_path: Path) -> None:
    contract = _contract(tmp_path)

    spec = build_film_spec(_edl(output_fps="30"), _plan(), contract)

    assert spec.film_id == "main-film"
    assert [s.id for s in spec.scenes] == ["hook-card-1", "chapter-1"]
    assert [s.start_in_output for s in spec.scenes] == [0.0, 5.0]
    assert spec.offset("chapter-1") == pytest.approx(1.8)
    assert spec.duration == pytest.approx(3.8)
    assert (spec.width, spec.height, spec.fps, spec.conform_to_fps) == (W, H, 30, None)
    assert spec.font_family == "Lato"
    assert spec.palette.main == "#E63946"
    assert len({c.casefold() for c in spec.palette.colours()}) == 4
    assert spec.extended_letters == "ąćęłś"
    assert spec.brand_contract_sha256 == contract.project_config_sha256
    assert spec.safe_margins_px["left"] == round(contract.safe_margins["left"] / 100 * W)
    assert set(spec.reserved_zones_px) == {"reels"}
    assert spec.brand_upload == "none" and spec.logo_file is None and spec.font_file is None


def test_brand_files_are_named_only_under_a_recorded_basis(tmp_path: Path) -> None:
    flagged = build_film_spec(_edl(), _plan(), _contract(tmp_path), allow_brand_upload=True)
    configured = build_film_spec(
        _edl(), _plan(), _contract(tmp_path / "b", "brand_asset_upload: allowed\n")
    )

    assert flagged.brand_upload == "explicit_flag"
    assert configured.brand_upload == "project_config"
    assert flagged.logo_file and flagged.logo_file.endswith("logo.png")
    assert configured.font_file and configured.font_file.endswith("Lato.ttf")
    with pytest.raises(ValueError, match="only when their upload is permitted"):
        FilmSpec.model_validate({**flagged.model_dump(), "brand_upload": "none"})


@pytest.mark.parametrize(
    ("declared", "fps", "conform"),
    [("30", 30, None), ("24", 24, None), ("60", 60, None), ("25", 60, "25"),
     ("30000/1001", 60, "30000/1001"), (None, 60, None)],
)  # fmt: skip
def test_the_film_rate_is_one_motion_exports(declared, fps, conform) -> None:
    spec = build_film_spec(_edl(output_fps=declared), _plan(), None)

    assert (spec.fps, spec.conform_to_fps) == (fps, conform)


def test_a_graphic_over_the_picture_or_too_short_is_refused() -> None:
    plan = _plan()

    with pytest.raises(ValidationError, match="lower_third sits over the picture"):
        build_film_spec(_edl(), plan, None, types=["lower_third"])
    with pytest.raises(ValidationError, match="unknown graphic type"):
        build_film_spec(_edl(), plan, None, types=["sparkles"])
    with pytest.raises(ValidationError, match="no cta"):
        build_film_spec(_edl(), plan, None, types=["cta"])
    short = MotionPlan(
        rationale="r",
        elements=[MotionElement(type="cta", start=8.0, end=8.6, text="Obserwuj", reason="r")],
    )
    with pytest.raises(ValidationError, match="under 1 s"):
        build_film_spec(_edl(), short, None)


def test_the_digest_ignores_when_and_by_whom_it_was_written() -> None:
    first = build_film_spec(_edl(), _plan(), None)
    second = build_film_spec(_edl(), _plan(), None, claude_motion=CapabilityState.AVAILABLE)
    retitled = build_film_spec(_edl(), _plan(), None, title="Another")

    assert first.digest() == second.digest()
    assert first.digest() != retitled.digest()


def test_writing_the_spec_gives_motion_its_own_files_and_registers_it(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, _contract(tmp_path))
    spec = build_film_spec(load_artifact(EDL, ws.edl), _plan(), load_artifact(
        BrandContract, ws.brand_contract))  # fmt: skip

    path = write_film_spec(ws, spec)

    folder = path.parent
    scenes = json.loads((folder / "scenes.json").read_text(encoding="utf-8"))
    assert (scenes["width"], scenes["height"], scenes["fps"]) == (W, H, 30)
    assert [(s["id"], s["dur"]) for s in scenes["scenes"]] == [
        ("hook-card-1", 1.8),
        ("chapter-1", 2.0),
    ]
    assert scenes["fonts"]["sans"]["family"] == "Lato"
    assert scenes["palettes"] == [spec.palette.colours()] and scenes["theirs"] == 1
    css = (folder / "base.css").read_text(encoding="utf-8")
    assert f"--main:{spec.palette.main}" in css
    assert load_registry(ws).pending() == [("main-film", "hook-card-1"), ("main-film", "chapter-1")]
    assert _pending_films(SimpleNamespace(workspace=str(ws.root))) == [
        "main-film/hook-card-1", "main-film/chapter-1"]  # fmt: skip


def test_an_old_edl_without_overlay_kinds_still_loads() -> None:
    raw = _edl().model_dump(mode="json")
    raw["overlays"] = [{"file": "x.mp4", "start_in_output": 1.0, "duration": 1.0}]

    edl = EDL.model_validate(raw)

    assert edl.overlays[0].kind is OverlayKind.MEDIA


# -- import, removal, evidence --------------------------------------------------


@pytest.fixture
def specified(tmp_path: Path) -> Workspace:
    ws = _workspace(tmp_path, _contract(tmp_path))
    spec = build_film_spec(
        load_artifact(EDL, ws.edl), _plan(), load_artifact(BrandContract, ws.brand_contract)
    )
    write_film_spec(ws, spec)
    return ws


@requires_ffmpeg
def test_import_cuts_each_scene_and_puts_it_in_place_of_its_graphic(
    tmp_path: Path, specified: Workspace
) -> None:
    export = _export(tmp_path / "film.mp4", [("red", 1.8), ("blue", 2.0)])

    segments = import_film(specified, export, film_id="main-film", font_used="Lato")

    hook, chapter = segments
    assert (hook.scene_id, chapter.scene_id) == ("hook-card-1", "chapter-1")
    assert chapter.offset_in_film == pytest.approx(1.8)
    assert palette_share(Path(hook.path), ["#FF0000"]) > 0.9
    assert palette_share(Path(chapter.path), ["#0000FF"]) > 0.9
    assert hook.duration == pytest.approx(1.8, abs=0.04)
    edl = load_artifact(EDL, specified.edl)
    films = [o for o in edl.overlays if o.kind is OverlayKind.MOTION_FILM]
    assert [(o.start_in_output, o.duration, o.scale_width) for o in films] == [
        (0.0, 1.8, W), (5.0, 2.0, W)]  # fmt: skip
    plan = load_artifact(MotionPlan, specified.motion_plan)
    assert [e.type.value for e in plan.elements] == ["lower_third", "stat"]
    assert hook.replaced_element is not None and hook.replaced_element.type.value == "hook_card"
    assert load_registry(specified).pending() == []
    evidence = segment_evidence(specified, edl)
    assert [e["scene_id"] for e in evidence] == ["hook-card-1", "chapter-1"]
    assert all(e["sha256"] == e["recorded_sha256"] for e in evidence)

    again = import_film(specified, export, film_id="main-film", font_used="Lato")

    assert len(load_artifact(EDL, specified.edl).overlays) == 2
    assert again[0].replaced_element == hook.replaced_element


@requires_ffmpeg
def test_import_refuses_another_size_length_film_or_an_edited_spec(
    tmp_path: Path, specified: Workspace
) -> None:
    landscape = _export(tmp_path / "wide.mp4", [("red", 3.8)], size=(H, W))
    short = _export(tmp_path / "short.mp4", [("red", 3.0)])
    right = _export(tmp_path / "right.mp4", [("red", 1.8), ("blue", 2.0)])

    with pytest.raises(ValidationError, match="Another size is another film"):
        import_film(specified, landscape, film_id="main-film", font_used="Lato")
    with pytest.raises(ValidationError, match=r"add up to 3\.800 s"):
        import_film(specified, short, film_id="main-film", font_used="Lato")
    with pytest.raises(ValidationError, match="no Motion film 'other'"):
        import_film(specified, right, film_id="other", font_used="Lato")
    with pytest.raises(ValidationError, match="no scene nope"):
        import_film(specified, right, film_id="main-film", font_used="Lato", scene_ids=["nope"])
    spec_path = Path(load_registry(specified).film("main-film").spec_path)
    spec = load_artifact(FilmSpec, spec_path)
    save_artifact(spec.model_copy(update={"title": "edited by hand"}), spec_path)
    with pytest.raises(ValidationError, match="changed after it was written"):
        import_film(specified, right, film_id="main-film", font_used="Lato")


@requires_ffmpeg
def test_removing_a_segment_restores_its_graphic(tmp_path: Path, specified: Workspace) -> None:
    export = _export(tmp_path / "film.mp4", [("red", 1.8), ("blue", 2.0)])
    import_film(specified, export, film_id="main-film", font_used="Lato")

    removed = remove_film_segment(specified, "main-film", "hook-card-1")

    assert removed.scene_id == "hook-card-1"
    plan = load_artifact(MotionPlan, specified.motion_plan)
    assert [e.type.value for e in plan.elements] == ["hook_card", "lower_third", "stat"]
    overlays = load_artifact(EDL, specified.edl).overlays
    assert [o.start_in_output for o in overlays] == [5.0]
    assert load_registry(specified).pending() == [("main-film", "hook-card-1")]
    with pytest.raises(ValidationError, match="no imported segment"):
        remove_film_segment(specified, "main-film", "hook-card-1")


@requires_ffmpeg
def test_a_film_in_place_of_the_held_end_card_keeps_the_hold(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, _contract(tmp_path))
    card = MotionElement(type="end_card", start=8.0, end=10.5, text="Do zobaczenia",
                         hold=True, reason="Sign-off.")  # fmt: skip
    save_artifact(MotionPlan(rationale="r", elements=[card]), ws.motion_plan)
    held = sync_end_hold(ws, load_artifact(EDL, ws.edl))
    assert held.end_hold == pytest.approx(2.5)
    contract = load_artifact(BrandContract, ws.brand_contract)
    write_film_spec(ws, build_film_spec(held, load_artifact(MotionPlan, ws.motion_plan), contract))
    export = _export(tmp_path / "film.mp4", [("blue", 2.5)])

    import_film(ws, export, film_id="main-film", font_used="Lato")

    assert load_artifact(MotionPlan, ws.motion_plan).elements == []
    # The render and every compile run this; the film must still have its end.
    kept = sync_end_hold(ws, load_artifact(EDL, ws.edl))
    assert kept.end_hold == pytest.approx(2.5)
    assert load_artifact(EDL, ws.edl).end_hold == pytest.approx(2.5)


@requires_ffmpeg
def test_a_missing_or_altered_segment_stops_the_render(
    tmp_path: Path, specified: Workspace
) -> None:
    export = _export(tmp_path / "film.mp4", [("red", 1.8), ("blue", 2.0)])
    hook, _ = import_film(specified, export, film_id="main-film", font_used="Lato")
    edl = load_artifact(EDL, specified.edl)

    Path(hook.path).write_bytes(Path(hook.path).read_bytes() + b"tampered")
    with pytest.raises(ValidationError, match="changed after import"):
        segment_evidence(specified, edl)
    Path(hook.path).unlink()
    with pytest.raises(ValidationError, match="missing at"):
        segment_evidence(specified, edl)
    elsewhere = Overlay(
        file="elsewhere.mp4", kind=OverlayKind.MOTION_FILM, start_in_output=0, duration=1
    )
    stray = edl.model_copy(update={"overlays": [elsewhere]})
    with pytest.raises(ValidationError, match="no import records it"):
        segment_evidence(specified, stray)


# -- brand QA --------------------------------------------------------------------


def _checks(contract: BrandContract, segments: list[dict]) -> dict[str, tuple[bool, bool]]:
    found: dict[str, tuple[bool, bool]] = {}

    def add(name: str, ok: bool, message: str, *, warning: bool = False) -> None:
        found[name] = (ok, warning)

    render = RenderManifest(
        output="o.mp4", edl="e", rendered_at="t", duration=1, width=W, height=H,
        frame_rate="30", motion_film_segments=segments,
    )  # fmt: skip
    _check_film_segments(add, contract, render)
    return found


@requires_ffmpeg
def test_brand_qa_checks_the_segment_against_the_contract(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    branded = _export(tmp_path / "branded.mp4", [("0xE63946", 1.0)])
    foreign = _export(tmp_path / "foreign.mp4", [("0x22AA22", 1.0)])
    base = {
        "film_id": "f", "scene_id": "hook-card-1", "sha256": "a" * 64,
        "recorded_sha256": "a" * 64, "width": W, "height": H, "font_used": "Lato",
        "brand_contract_sha256": contract.project_config_sha256, "brand_upload": "none",
    }  # fmt: skip

    good = _checks(contract, [{**base, "path": str(branded)}])
    bad = _checks(
        contract,
        [{**base, "path": str(foreign), "recorded_sha256": "b" * 64, "font_used": "Arial",
          "width": 1080, "brand_contract_sha256": "c" * 64}],
    )  # fmt: skip

    prefix = "motion film f/hook-card-1"
    assert all(ok for ok, _ in good.values()), good
    assert bad[f"{prefix} unchanged since import"] == (False, False)
    assert bad[f"{prefix} size"] == (False, False)
    assert bad[f"{prefix} font"] == (False, False)
    assert bad[f"{prefix} made under the current brand"] == (False, True)
    assert bad[f"{prefix} in the brand's colours"] == (False, True)


# -- CLI --------------------------------------------------------------------------


@requires_ffmpeg
def test_the_cli_specifies_imports_reports_and_removes(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, _contract(tmp_path))
    runner = CliRunner()
    root = str(ws.root)

    refused = runner.invoke(app, ["motion", "film", "spec", "-w", root,
                                  "--claude-motion", "unavailable"])  # fmt: skip
    spec = runner.invoke(app, ["motion", "film", "spec", "-w", root, "--scene", "hook_card",
                               "--claude-motion", "available"])  # fmt: skip
    waiting = runner.invoke(app, ["motion", "film", "status", "-w", root, "--json"])
    export = _export(tmp_path / "film.mp4", [("red", 1.8)])
    imported = runner.invoke(app, ["motion", "film", "import", str(export), "-w", root,
                                   "--film-id", "main-film", "--font-used", "Lato"])  # fmt: skip
    respec = runner.invoke(app, ["motion", "film", "spec", "-w", root])
    removed = runner.invoke(app, ["motion", "film", "remove", "hook-card-1", "-w", root,
                                  "--film-id", "main-film"])  # fmt: skip

    assert refused.exit_code == 1 and "keep the Remotion graphics" in refused.output
    assert spec.exit_code == 0, spec.output
    assert "letters beyond the built-in faces" in spec.output
    assert '"pending": [\n    "main-film/hook-card-1"\n  ]' in waiting.output
    assert imported.exit_code == 0, imported.output
    assert "replaces hook_card" in imported.output
    assert respec.exit_code == 1 and "already has imported segments" in respec.output
    assert removed.exit_code == 0 and "restored hook_card" in removed.output
