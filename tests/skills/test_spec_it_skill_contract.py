"""Contract test for the ``spec-it`` skill: its SKILL.md frontmatter, its API launcher, its driver and
its models.

The skill's models and API are imported, never copied: a literal pinned here would drift from the module that
defines it.
"""
from __future__ import annotations

import re

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
    assert re.search(rf"\bat {spec_it_models.MAX_LINES}\s+lines\b", body)
    assert re.search(rf"\b{spec_it_models.TARGET_LINES}-line\s+target\b", body)
