"""Pre-0.4 project configuration must migrate loudly, never by guessing."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from social_video.config_migration import migrate_project_config, plan_migration
from social_video.errors import ConfigMigrationError
from social_video.project_config import compile_brand_contract, load_project_config
from social_video.workspace.layout import Workspace

#: The shape a project used before 0.4, when the config was discovery context
#: and prose was welcome because nothing rendered from it.
LEGACY_CONFIG = """brand_name: Acme
content_language: pl
editing_profile: calm-expert
font: assets/fonts/Inter-Regular.ttf
logo: assets/logo.svg
caption_style:
  position: lower_safe_zone
  outline_or_shadow: subtle
  bottom_margin_pct: 0.15
punch_in_intensity: restrained
broll_density: low
music_policy: only licensed library tracks
sfx_policy: minimal, transitions only
default_fps_policy: match source
safe_margins:
  top: 0.06
  bottom: 0.15
preferred_output_directory: /mnt/d/out
"""

#: The same project after a human answered every question the error asks.
MIGRATED_CONFIG = """schema_version: 1
brand_name: Acme
content_language: pl
editing_profile: calm-expert
font: Inter
font_file: assets/fonts/Inter-Regular.ttf
logo_file: assets/logo.svg
caption_style:
  position: lower_safe_zone
  outline_or_shadow: outline
  bottom_margin_pct: 15
punch_in_intensity: 0.25
broll_density: 0.2
music_policy: optional
sfx_policy: optional
default_fps_policy: "30"
safe_margins:
  top: 6
  bottom: 15
delivery_output: /mnt/d/out
"""


def _yaml(text: str) -> dict:
    import yaml

    return yaml.safe_load(text)


def _project(tmp_path: Path, config_text: str) -> Path:
    project = tmp_path / "project"
    (project / "assets/fonts").mkdir(parents=True)
    (project / "assets/fonts/Inter-Regular.ttf").write_bytes(b"fixture-font")
    (project / "assets/logo.svg").write_text("<svg></svg>", encoding="utf-8")
    (project / ".social-video").mkdir()
    config = project / ".social-video/config.yaml"
    config.write_text(config_text, encoding="utf-8")
    return config


def _one_line(output: str) -> str:
    """Console output with its wrapping undone.

    Rich wraps to the terminal width, so on a runner with a long temporary
    directory the message a user reads on one line arrives split across two.
    """
    return " ".join(output.split())


def test_legacy_config_names_every_field_that_needs_a_decision(tmp_path: Path) -> None:
    config = _project(tmp_path, LEGACY_CONFIG)

    with pytest.raises(ConfigMigrationError) as caught:
        load_project_config(config)

    message = str(caught.value)
    for field in (
        "caption_style.outline_or_shadow",
        "caption_style.bottom_margin_pct",
        "punch_in_intensity",
        "broll_density",
        "music_policy",
        "sfx_policy",
        "default_fps_policy",
        "safe_margins.top",
        "safe_margins.bottom",
        "font",
    ):
        assert field in message, field
    assert "docs/migrations/0.4-brand-contract.md" in message
    assert "config validate" in message


def test_migration_doc_recipe_alone_is_still_reported_as_incomplete(tmp_path: Path) -> None:
    """Adding schema_version and renaming two fields must not look sufficient."""
    text = LEGACY_CONFIG.replace("logo:", "logo_file:").replace(
        "preferred_output_directory:", "delivery_output:"
    )
    config = _project(tmp_path, "schema_version: 1\n" + text)

    with pytest.raises(ConfigMigrationError, match=re.escape("still holds pre-0.4 values")):
        load_project_config(config)


def test_fractional_margins_are_refused_rather_than_silently_rescaled() -> None:
    _, issues = plan_migration({"safe_margins": {"top": 0.06}, "caption_style": {}})

    (issue,) = issues
    assert issue.field == "safe_margins.top"
    assert "0.06%" in issue.reason and "6%" in issue.reason
    assert "write 6" in issue.instruction


@pytest.mark.parametrize("value", [0, 6, 15, 45])
def test_percentage_margins_are_left_alone(value: int) -> None:
    migrated, issues = plan_migration({"safe_margins": {"top": value}})

    assert issues == []
    assert migrated["safe_margins"]["top"] == value


def test_renames_and_yaml_scalar_shapes_carry_over_silently() -> None:
    migrated, issues = plan_migration(
        {
            "logo": "assets/logo.svg",
            "preferred_output_directory": "/mnt/d/out",
            "default_fps_policy": 30,
            "music_policy": "NONE",
        }
    )

    assert issues == []
    assert migrated == {
        "schema_version": 1,
        "logo_file": "assets/logo.svg",
        "delivery_output": "/mnt/d/out",
        "default_fps_policy": "30",
        "music_policy": "none",
    }


def test_conflicting_old_and_new_name_is_reported_instead_of_dropped() -> None:
    _, issues = plan_migration({"logo": "old.svg", "logo_file": "new.svg"})

    (issue,) = issues
    assert issue.field == "logo"
    assert "logo_file" in issue.reason


def test_font_path_must_be_split_into_family_and_file() -> None:
    _, issues = plan_migration({"font": "assets/fonts/Inter-Regular.ttf"})

    (issue,) = issues
    assert issue.field == "font"
    assert "font_file: assets/fonts/Inter-Regular.ttf" in issue.instruction


def test_unknown_key_is_reported_with_the_closest_supported_field() -> None:
    _, issues = plan_migration({"brand_colours": ["#28BCA5"]})

    (issue,) = issues
    assert issue.field == "brand_colours"
    assert "'brand_colors'" in issue.instruction


def test_descriptive_policy_keeps_its_three_executable_choices() -> None:
    _, issues = plan_migration({"music_policy": "only licensed library tracks"})

    (issue,) = issues
    assert "'none', 'optional', 'required'" in issue.instruction


def test_unsupported_schema_version_is_named() -> None:
    _, issues = plan_migration({"schema_version": 2})

    assert [issue.field for issue in issues] == ["schema_version"]


def test_migrated_config_compiles_into_the_executable_contract(tmp_path: Path) -> None:
    config = _project(tmp_path, MIGRATED_CONFIG)
    project = config.parent.parent

    contract = compile_brand_contract(config, Workspace.at(project / "edit"), project_root=project)

    assert contract.brand.captions.font_family == "Inter"
    assert contract.brand.captions.margin_pct == 15
    assert contract.safe_margins["top"] == 6
    assert contract.brand.motion_intensity == 0.25
    assert contract.music_policy == "optional"
    assert contract.output_fps == "30/1"
    # The contract stores a resolved path, and resolving is native: on Windows
    # a rootless POSIX path lands on the current drive.
    assert contract.delivery_output == str(Path("/mnt/d/out").resolve())


def test_migrate_does_not_mutate_the_caller_mapping() -> None:
    raw = _yaml(LEGACY_CONFIG)
    before = _yaml(LEGACY_CONFIG)

    with pytest.raises(ConfigMigrationError):
        migrate_project_config(raw, source="config.yaml")

    assert raw == before


def test_config_migrate_command_reports_and_exits_nonzero(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from social_video.cli import app

    _project(tmp_path, LEGACY_CONFIG)
    result = CliRunner().invoke(app, ["config", "migrate", str(tmp_path / "project")])

    assert result.exit_code == 1
    assert "rename logo -> logo_file" in _one_line(result.stdout)
    assert "punch_in_intensity" in _one_line(result.stdout)


def test_config_migrate_command_accepts_a_migrated_config(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from social_video.cli import app

    _project(tmp_path, MIGRATED_CONFIG)
    result = CliRunner().invoke(app, ["config", "migrate", str(tmp_path / "project")])

    assert result.exit_code == 0
    assert "needs no manual migration" in _one_line(result.stdout)


def test_the_shipped_template_needs_no_migration() -> None:
    import yaml

    from social_video.project_config import DEFAULT_CONFIG

    migrated, issues = plan_migration(yaml.safe_load(DEFAULT_CONFIG))

    assert issues == []
    assert migrated["schema_version"] == 1
