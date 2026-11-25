"""The strap-skills SKILL.md covers both profiles and states the project profile's prerequisites."""
from __future__ import annotations

from conftest import PLUGIN_ROOT
from harness_lib.skill_parts import skill_parts

SKILL = PLUGIN_ROOT / "skills" / "strap-skills" / "SKILL.md"


def test_description_is_not_limited_to_harness_skills() -> None:
    description = skill_parts(SKILL)[0]["description"].strip("\"'")
    assert "harness skill" not in description, description
    assert "project skill" in description, description


def test_body_names_the_target_key_and_the_launcher() -> None:
    body = skill_parts(SKILL)[1]
    assert "strap.target" in body
    assert 'harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file' in body


def test_body_states_the_project_prerequisites() -> None:
    body = skill_parts(SKILL)[1]
    assert "HARNESS_PY" in body and "pydantic>=2" in body
    assert "raise `ImportError` when the file is absent" in body
