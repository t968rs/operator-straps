"""The ``SkillSpec`` target field: a project spec round-trips, a harness spec's file text is unchanged.

A spec carries exactly one of ``plugin_dir`` (harness profile) and ``target`` (project profile). A harness
spec's dump has no ``target`` key, so every spec already on disk keeps its canonical text, driver digest and
seal.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from conftest import REPO_ROOT
from harness_lib.strap_models import (
    SkillSpec, SkillTarget, SpecMode, driver_digest, dump_spec, load_spec, seal_broken,
)

WALK_ROOTS = ("docs/plans/strap/",)
NAME = "demo-skill"
EXISTING = sorted((REPO_ROOT / "docs" / "plans" / "strap").glob("*/SkillSpec.json"))


def _target() -> SkillTarget:
    return SkillTarget(skills_dir=".claude/skills", agents_dir=".claude/agents")


def test_project_spec_round_trips_through_its_dump() -> None:
    spec = SkillSpec(name=NAME, mode=SpecMode.NEW, target=_target())
    text = dump_spec(spec)
    assert SkillSpec.model_validate_json(text) == spec
    data = json.loads(text)
    assert data["plugin_dir"] is None
    assert data["target"] == {"skills_dir": ".claude/skills", "agents_dir": ".claude/agents"}


def test_harness_spec_dump_has_no_target_key() -> None:
    spec = SkillSpec(name=NAME, mode=SpecMode.NEW, plugin_dir="plugins/harness")
    assert "target" not in json.loads(dump_spec(spec))


@pytest.mark.parametrize("fields", [{}, {"plugin_dir": "plugins/harness", "target": _target()}],
                         ids=["neither", "both"])
def test_spec_needs_exactly_one_of_plugin_dir_and_target(fields: dict) -> None:
    with pytest.raises(ValidationError):
        SkillSpec(name=NAME, mode=SpecMode.NEW, **fields)


def test_existing_specs_are_found() -> None:
    assert len(EXISTING) >= 5, [path.as_posix() for path in EXISTING]


@pytest.mark.parametrize("path", EXISTING, ids=[path.parent.name for path in EXISTING])
def test_existing_spec_keeps_its_text_digest_and_seal(path) -> None:
    spec = load_spec(path)
    assert path.read_text(encoding="utf-8") == dump_spec(spec)
    assert spec.driver_digest == driver_digest(spec)
    assert not seal_broken(spec)
