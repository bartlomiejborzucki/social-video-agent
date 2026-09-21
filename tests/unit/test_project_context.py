from __future__ import annotations

from pathlib import Path

import pytest

from social_video.config_migration import LEGACY_ALIASES
from social_video.errors import ValidationError
from social_video.project_config import compile_brand_contract
from social_video.project_context import discover_project_context, resolve_project_root
from social_video.schemas.config import ProjectVideoConfig
from social_video.schemas.project_context import ProjectConfig
from social_video.workspace.layout import Workspace


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _discover(project: Path, tmp_path: Path, *, refresh: bool = False):
    return discover_project_context(
        project,
        Workspace.at(tmp_path / "workspaces" / project.name / "edit"),
        refresh=refresh,
    )


def test_project_a_finds_high_value_guidance_and_assets(tmp_path: Path) -> None:
    project = tmp_path / "project-a"
    _write(project / "AGENTS.md", "Use calm, educational video editing.")
    _write(project / "docs/brandbook.md", "Brand font: Inter. Brand color: yellow.")
    _write(project / "docs/video-guidelines.md", "Captions stay in the lower safe zone.")
    _write(project / "assets/logo.svg", "<svg></svg>")
    _write(project / "assets/fonts/Inter/Inter-Regular.ttf", "fixture")
    _write(project / "input.mp4", "fixture")

    context, sources = _discover(project, tmp_path)
    paths = {source.path for source in sources.sources}

    assert context.target_project_root == str(project.resolve())
    assert context.applicable_agents_files == ["AGENTS.md"]
    assert "docs/brandbook.md" in paths
    assert "docs/video-guidelines.md" in paths
    assert "assets/logo.svg" in context.logos
    assert "assets/fonts/Inter/Inter-Regular.ttf" in context.fonts
    assert context.unknowns == []


def test_project_b_uses_defaults_without_blocking(tmp_path: Path) -> None:
    project = tmp_path / "project-b"
    _write(project / "README.md", "Small utility with no media or brand guidance.")
    _write(project / "input.mp4", "fixture")

    context, sources = _discover(project, tmp_path)

    assert sources.sources == []
    assert context.explicit_config is None
    assert context.unknowns == [
        "No explicit brandbook or project-specific video guideline was found."
    ]


def test_project_c_ignores_vendor_tree_and_finds_nested_docs(tmp_path: Path) -> None:
    project = tmp_path / "project-c"
    _write(project / "brandbook.pdf", "%PDF fixture")
    _write(project / "docs/social/editing.md", "Video editing: slow social cuts.")
    _write(project / "node_modules/package/brandbook.md", "Must never be read.")

    _, sources = _discover(project, tmp_path)
    paths = {source.path for source in sources.sources}

    assert "brandbook.pdf" in paths
    assert "docs/social/editing.md" in paths
    assert not any(path.startswith("node_modules/") for path in paths)


def test_project_d_supports_polish_unicode_paths(tmp_path: Path) -> None:
    project = tmp_path / "projekt-żółty"
    _write(project / "docs/księga-marki.md", "Czcionka i kolor marki.")
    _write(project / "docs/zasady-montażu.md", "Montaż rolek i napisy.")
    _write(project / "assets/logo-żółte.svg", "<svg></svg>")

    context, sources = _discover(project, tmp_path)
    paths = {source.path for source in sources.sources}

    assert "docs/księga-marki.md" in paths
    assert "docs/zasady-montażu.md" in paths
    assert context.logos == ["assets/logo-żółte.svg"]


def test_project_e_never_scans_external_skill_root(tmp_path: Path) -> None:
    target = tmp_path / "customer-project"
    skill_root = tmp_path / "installed-skill"
    _write(target / "README.md", "Customer project.")
    _write(skill_root / "README.md", "Brand colors: red. Use meme cuts.")
    _write(skill_root / "assets/logo.svg", "<svg></svg>")

    context, sources = _discover(target, tmp_path)

    assert context.target_project_root == str(target.resolve())
    assert all("installed-skill" not in source.path for source in sources.sources)
    assert context.known_assets == []


def test_project_f_explicit_config_wins_and_loads_direct_references(tmp_path: Path) -> None:
    project = tmp_path / "project-f"
    _write(project / "brand.md", "Brand name: Heuristic Name. Font: Arial.")
    _write(project / "private/style.txt", "Calm edits and sparse captions.")
    _write(project / "private/mark.bin", "logo fixture")
    _write(
        project / "social-video.yaml",
        "\n".join(
            [
                "brand_name: Explicit Name",
                "font: Inter",
                "editing_profile: calm",
                "editing_guide: private/style.txt",
                "logo: private/mark.bin",
                "model_budget: economical",
            ]
        ),
    )

    context, sources = _discover(project, tmp_path)

    assert context.explicit_config == "social-video.yaml"
    assert context.brand == {"name": "Explicit Name"}
    assert context.fonts == ["Inter"]
    assert context.editing_guidelines["editing_profile"] == "calm"
    assert "private/style.txt" in context.style_sources
    assert any(source.path == "private/style.txt" for source in sources.sources)
    assert "private/mark.bin" in context.known_assets
    assert any(source.path == "private/mark.bin" for source in sources.sources)
    assert any(
        claim.key == "name"
        and claim.value == "Explicit Name"
        and claim.source == "social-video.yaml"
        and claim.confidence.value == "explicit"
        for claim in context.claims
    )


def test_context_cache_reuses_and_refreshes_on_relevant_change(tmp_path: Path) -> None:
    project = tmp_path / "cached-project"
    guide = _write(project / "docs/video-guide.md", "Calm video editing.")
    context_1, _ = _discover(project, tmp_path)
    context_2, _ = _discover(project, tmp_path)
    guide.write_text("Fast video editing with captions.", encoding="utf-8")
    context_3, _ = _discover(project, tmp_path)

    assert context_1.cache_status == "refreshed"
    assert context_2.cache_status == "reused"
    assert context_3.cache_status == "refreshed"
    assert context_3.source_fingerprint != context_1.source_fingerprint


def test_context_cache_does_not_scan_its_own_workspace(tmp_path: Path) -> None:
    project = tmp_path / "self-contained"
    _write(project / "docs/brand.md", "Brand voice and video guidance.")
    workspace = Workspace.at(project / "edit")

    context_1, sources_1 = discover_project_context(project, workspace)
    context_2, sources_2 = discover_project_context(project, workspace)

    assert context_1.cache_status == "refreshed"
    assert context_2.cache_status == "reused"
    assert sources_1.fingerprint == sources_2.fingerprint
    assert not any(source.path.startswith("edit/") for source in sources_2.sources)


def test_project_root_is_bounded_to_explicit_path_or_nearest_git(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "a/b"
    nested.mkdir(parents=True)
    (repo / ".git").mkdir()

    assert resolve_project_root(cwd=nested) == repo.resolve()
    assert resolve_project_root(nested) == nested.resolve()
    with pytest.raises(ValidationError, match="not a directory"):
        resolve_project_root(tmp_path / "missing")


def test_config_reference_cannot_escape_project(tmp_path: Path) -> None:
    project = tmp_path / "bounded"
    _write(project / "social-video.yaml", "brandbook: ../secret.md")
    _write(tmp_path / "secret.md", "Private")

    with pytest.raises(ValidationError, match="leaves target project root"):
        _discover(project, tmp_path)


def test_missing_configured_asset_is_reported_as_unknown(tmp_path: Path) -> None:
    project = tmp_path / "missing-asset"
    _write(project / "social-video.yaml", "logo: assets/missing-logo.svg")

    context, _ = _discover(project, tmp_path)

    assert context.unknowns == [
        "Configured local context file was not found: assets/missing-logo.svg"
    ]


def test_symlinked_file_outside_project_is_not_read(tmp_path: Path) -> None:
    project = tmp_path / "symlink-bounded"
    project.mkdir()
    secret = _write(tmp_path / "secret-brandbook.md", "Secret brand guidance")
    (project / "brandbook.md").symlink_to(secret)

    context, sources = _discover(project, tmp_path)

    assert sources.sources == []
    assert context.style_sources == []


def test_discovery_and_executable_config_schemas_stay_in_step() -> None:
    """`context inspect` must not reject a field `config validate` compiles."""
    discovery = set(ProjectConfig.model_fields)
    executable = set(ProjectVideoConfig.model_fields)

    assert executable - discovery == set()
    assert discovery - executable == set(LEGACY_ALIASES)


def test_same_config_passes_context_inspect_and_config_validate(tmp_path: Path) -> None:
    project = tmp_path / "both-paths"
    _write(project / "assets/Lato.ttf", "fixture-font")
    _write(project / "assets/logo.svg", "<svg></svg>")
    _write(project / "docs/brandbook.md", "Brand font: Lato.")
    _write(
        project / ".social-video/config.yaml",
        "\n".join(
            [
                "schema_version: 1",
                "brand_name: Both Paths",
                "font: Lato",
                "font_file: assets/Lato.ttf",
                "logo_file: assets/logo.svg",
                "logo_usage: optional",
                "brandbook: docs/brandbook.md",
                "image_generation_policy: optional",
                "target_platforms: [reels, shorts]",
                "music_policy: optional",
                "sfx_policy: none",
                "punch_in_intensity: 0.25",
                "broll_density: 0",
                "safe_margins: {top: 6, bottom: 15}",
                'default_aspect_ratio: "9:16"',
                'default_resolution: "1080x1920"',
                'default_fps_policy: "30"',
            ]
        ),
    )

    context, _ = _discover(project, tmp_path)
    contract = compile_brand_contract(
        project / ".social-video/config.yaml",
        Workspace.at(tmp_path / "contract-workspace"),
        project_root=project,
    )

    assert context.explicit_config == ".social-video/config.yaml"
    assert context.visual_style["image_generation_policy"] == "optional"
    assert context.output_requirements["target_platforms"] == ["reels", "shorts"]
    assert context.logos == ["assets/logo.svg"]
    assert context.fonts == ["Lato", "assets/Lato.ttf"]
    assert context.config["image_generation_policy"] == "optional"
    assert contract.image_generation_enabled is True
    assert contract.target_platforms == ["reels", "shorts"]


def test_reports_project_keeps_the_scan_on_brand_sources(tmp_path: Path) -> None:
    project = tmp_path / "reports-project"
    _write(project / "AGENTS.md", "Project instructions.")
    _write(
        project / ".social-video/config.yaml",
        "\n".join(
            [
                "brand_name: Acme",
                "brandbook: docs/brandbook.md",
                "editing_guide: docs/przewodnik-montazu.md",
                "logo_file: assets/logo.svg",
            ]
        ),
    )
    _write(project / "docs/brandbook.md", "Brand font: Inter.")
    _write(project / "docs/przewodnik-montazu.md", "Montaż: spokojne cięcia.")
    _write(project / "assets/logo.svg", "<svg></svg>")
    # Noise a reports-heavy project actually contains.
    _write(project / ".codex/skills/report-writer/SKILL.md", "---\nname: report-writer\n---\n")
    _write(
        project / ".codex/skills/report-writer/references/style.md",
        "Brand tone of voice, typography, colour palette, caption style guidance.",
    )
    _write(project / "skills/local-helper/SKILL.md", "---\nname: local-helper\n---\n")
    _write(project / "skills/local-helper/references/brand.md", "Brand guidelines for the tool.")
    _write(project / "reports/brand-audit-2026-q1.zip", "PK fixture")
    _write(project / "reports/raport-montaz.zip", "PK fixture")
    _write(project / "docs/q3-financial-report.pdf", "%PDF fixture")
    _write(
        project / "docs/meeting-notes.md",
        "Notes on the video call, social plans, the colour of the office, a vendor logo, "
        "the caption of a chart, editing a doc, tone, voice, font and the brand of laptop.",
    )

    context, sources = _discover(project, tmp_path)
    paths = [source.path for source in sources.sources]

    assert paths == [
        ".social-video/config.yaml",
        "AGENTS.md",
        "assets/logo.svg",
        "docs/brandbook.md",
        "docs/przewodnik-montazu.md",
    ]
    assert context.style_sources == [
        ".social-video/config.yaml",
        "docs/brandbook.md",
        "docs/przewodnik-montazu.md",
    ]
    assert not any(path.endswith(".zip") for path in paths)
    assert not any("skills/" in path for path in paths)


def test_config_named_guide_outranks_the_filename_heuristic(tmp_path: Path) -> None:
    project = tmp_path / "named-guide"
    _write(project / "docs/montaz.md", "Montaż: spokojne cięcia.")
    _write(project / "social-video.yaml", "editing_guide: docs/montaz.md")

    _, sources = _discover(project, tmp_path)
    guide = next(source for source in sources.sources if source.path == "docs/montaz.md")

    assert guide.confidence.value == "explicit"
    assert "referenced by explicit social-video configuration" in guide.signals


def test_newer_release_config_field_degrades_to_context(tmp_path: Path) -> None:
    """Discovery reports an unrecognised key; `config validate` is the gate."""
    project = tmp_path / "forward-compatible"
    _write(project / "social-video.yaml", "brand_name: Acme\nfuture_policy: enabled")

    context, _ = _discover(project, tmp_path)

    assert context.brand == {"name": "Acme"}
    assert context.config["future_policy"] == "enabled"
