"""The write-plan skill and its docs state ``plan.py archive`` (plan 2021, TASK-4; issues 284 and 283).

The SKILL.md has an **Archive.** step (developer's explicit ask, ``--remote``, the ``r1-<m>`` re-archive)
and an ``archive/<stem>/r1`` row in its tag table; the freeze ``-commit`` sentence names the agent as the one
who runs ``PLAN check``. The skill README lists the command, the schemas README names the archive tag, and
the PIP template's merge checklist names an actor on every step and includes the archive.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def skill(plugin_root: Path) -> str:
    return _flat(plugin_root / "skills" / "write-plan" / "SKILL.md")


def test_the_skill_has_an_archive_step(skill: str) -> None:
    assert "**Archive.**" in skill
    step = skill.split("**Archive.**", 1)[1].split("**What a record proves.**", 1)[0]
    assert "`PLAN archive <id> [--remote]`" in step
    assert "explicit ask" in step and "`archive/<stem>/r1-<m>`" in step
    assert "`untagged:`" in step and "`off-history:`" in step


def test_the_tag_table_names_the_archive_tag(skill: str) -> None:
    assert "| `archive/<stem>/r1`" in skill


def test_the_agent_runs_check_after_the_freeze_commit(skill: str) -> None:
    assert "after the developer commits the freeze run `PLAN check <id>`" not in skill
    assert "the agent runs `PLAN check <id>`" in skill


def test_the_skill_readme_and_schemas_readme_name_the_archive(plugin_root: Path) -> None:
    assert "`PLAN archive <id>" in _flat(plugin_root / "skills" / "write-plan" / "README.md")
    assert "`archive/<stem>/r1`" in _flat(plugin_root / "schemas" / "README.md")


def test_the_pip_template_merge_steps_name_an_actor(plugin_root: Path) -> None:
    text = (plugin_root / "schemas" / "PLANS_PIP_Template.md").read_text(encoding="utf-8")
    section = text.split("## Merge/Integration", 1)[1].split("## Schema Rules", 1)[0]
    steps = [line.strip() for line in section.splitlines() if re.match(r"^\s*\d+\. ", line)]
    assert steps, section
    for step in steps:
        assert re.match(r"^\d+\. \((developer|agent)\) ", step), step
    assert "plan.py archive {PLAN_ID}" in section
