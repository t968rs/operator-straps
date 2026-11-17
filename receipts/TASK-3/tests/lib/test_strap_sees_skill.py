"""The scenario ``sees_skill`` field: whether a run brief carries the SKILL.md.

Unset, it follows the role: the session sees the skill, a role agent sees only its agent file. An unset
value never reaches the dump, so every spec already on disk keeps its canonical text, driver digest and
seal; a set value is an authored field and round-trips.
"""
from __future__ import annotations

import json
from typing import Optional

import pytest
from pydantic import ValidationError

from conftest import REPO_ROOT
from harness_lib.strap_models import (
    Behavior, Scenario, SkillSpec, SpecMode, authored_digest, driver_digest, dump_spec, load_spec,
    seal_broken,
)

WALK_ROOTS = ("docs/plans/strap/",)
EXISTING = sorted((REPO_ROOT / "docs" / "plans" / "strap").glob("*/SkillSpec.json"))


def _scenario(role: str = "session", sees_skill: Optional[bool] = None) -> Scenario:
    return Scenario(id="SC-1", task="Edit the ledger.", tempts="edits the ledger", role=role,
                    pressures=["authority", "time", "pragmatic"],
                    sees_skill=sees_skill, judged=[{"act": "refuses", "of": "the ledger edit",
                                                    "expect_baseline": "absent", "expect_green": "present"}])


def _spec(scenario: Scenario) -> SkillSpec:
    behavior = Behavior(id="B1", statement="Refuses the ledger edit", kind="judgment", type="discipline",
                        rationale="A refusal no file state tells apart", scenarios=[scenario])
    return SkillSpec(name="demo-skill", mode=SpecMode.NEW, plugin_dir="plugins/harness", behaviors=[behavior])


@pytest.mark.parametrize(("role", "sees_skill", "expected"), [
    ("session", None, True), ("session", True, True),
    ("helper", None, False), ("helper", True, True), ("helper", False, False),
])
def test_skill_in_brief_follows_role_unless_set(role: str, sees_skill: Optional[bool],
                                                expected: bool) -> None:
    assert _scenario(role, sees_skill).skill_in_brief is expected


def test_session_scenario_refuses_sees_skill_false() -> None:
    with pytest.raises(ValidationError, match="sees_skill false needs a role"):
        _scenario("session", False)


def test_unset_sees_skill_is_absent_from_the_dump() -> None:
    [behavior] = json.loads(dump_spec(_spec(_scenario("helper"))))["behaviors"]
    assert "sees_skill" not in behavior["scenarios"][0]


def test_set_sees_skill_round_trips_and_is_authored() -> None:
    unset, kept = _spec(_scenario("helper")), _spec(_scenario("helper", True))
    text = dump_spec(kept)
    assert json.loads(text)["behaviors"][0]["scenarios"][0]["sees_skill"] is True
    assert SkillSpec.model_validate_json(text) == kept
    assert authored_digest(kept) != authored_digest(unset)


@pytest.mark.parametrize("path", EXISTING, ids=[path.parent.name for path in EXISTING])
def test_existing_spec_keeps_its_text_digest_and_seal(path) -> None:
    spec = load_spec(path)
    assert path.read_text(encoding="utf-8") == dump_spec(spec)
    assert spec.driver_digest == driver_digest(spec)
    assert not seal_broken(spec)
