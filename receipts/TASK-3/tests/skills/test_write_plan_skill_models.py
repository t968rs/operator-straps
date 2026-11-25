"""The write-plan skill teaches the model-first authoring path and never the hand-edited JSON one."""
from __future__ import annotations

import re
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def skill(plugin_root: Path) -> str:
    return (plugin_root / "skills" / "write-plan" / "SKILL.md").read_text(encoding="utf-8")


def test_step_three_is_a_heredoc_that_loads_copies_and_writes_the_plan(skill: str) -> None:
    assert 'PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/lib" sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" - <<\'EOF\'' in skill
    assert "plan_api.load(" in skill and "model_copy(update=" in skill and "deep=True" in skill
    assert "plan_api.write(" in skill


def test_the_skill_no_longer_tells_the_agent_to_edit_the_plan_json(skill: str) -> None:
    assert "Edit or Write on the plan file" not in skill


def test_the_skill_forbids_hand_edits_and_names_the_one_repair_exception(skill: str) -> None:
    assert re.search(r"never (?:edited|edit)[^.]*by hand", skill, re.IGNORECASE)
    assert "fails to load" in skill


def test_the_skill_has_a_common_mistakes_section(skill: str) -> None:
    assert "## Common mistakes" in skill
    section = skill.split("## Common mistakes", 1)[1].split("\n## ", 1)[0]
    for fragment in ("hand-edit exception", "existing item's status", "Guessing a `red` exception",
                     "use `{base}`", "without `deep=True`"):
        assert fragment in section


def test_the_skill_names_the_models_module_not_the_hand_written_schema(skill: str) -> None:
    assert "plan_models" in skill and "ActionPlan.schema.json" not in skill.split("## Related", 1)[0]
