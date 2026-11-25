"""Contract test for the ``spec-it`` skill: its SKILL.md frontmatter, its API launcher, its driver and
its models.

The skill's models and API are imported, never copied: a literal pinned here would drift from the module that
defines it.
"""
from __future__ import annotations

from datetime import date

from harness_lib import spec_it_api, spec_it_models
from harness_lib.project import plugin_root
from harness_lib.skill_parts import skill_parts

NAME = "spec-it"
SKILL = plugin_root() / "skills" / NAME / "SKILL.md"
LAUNCHER = 'scripts/skill_api.py" spec_it_api'
DRIVER = 'scripts/spec_it.py" check'


def test_frontmatter_names_the_skill_folder() -> None:
    keys = skill_parts(SKILL)[0]
    assert keys["name"].strip("\"'") == NAME


def test_description_is_filled() -> None:
    description = skill_parts(SKILL)[0].get("description", "").strip("\"'")
    assert description.startswith("Use when"), description


def test_api_heredoc_launches_the_skill_api() -> None:
    assert LAUNCHER in skill_parts(SKILL)[1]


def test_the_check_command_runs_the_driver() -> None:
    body = skill_parts(SKILL)[1]
    assert DRIVER in body
    assert (plugin_root() / "scripts" / "spec_it.py").is_file()


def test_api_exports_existing_names() -> None:
    missing = [name for name in spec_it_api.__all__ if not hasattr(spec_it_api, name)]
    assert not missing, missing


def test_the_skill_states_the_line_caps_the_model_enforces() -> None:
    body = skill_parts(SKILL)[1]
    assert str(spec_it_models.MAX_LINES) in body
    assert str(spec_it_models.TARGET_LINES) in body


def test_sheet_round_trips_through_its_page() -> None:
    sheet = spec_it_models.SpecSheet(title="T", day=date(2026, 1, 2), request="R.", goals=["G holds."])
    assert spec_it_models.parse_sheet(spec_it_models.render_sheet(sheet)) == sheet
