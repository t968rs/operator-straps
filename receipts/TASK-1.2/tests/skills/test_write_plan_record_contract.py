"""The write-plan skill states what a record proves: a seal, tree provenance, and ``verify`` for the rest.

``check`` proves that ``record`` wrote each status; whether the work is still in the code is ``verify``'s
question. The skill must say both, name ``--staged`` for staged lane work, and drop the old rule that tied a
COMPLETE item to a commit reachable from HEAD.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def skill(plugin_root: Path) -> str:
    text = (plugin_root / "skills" / "write-plan" / "SKILL.md").read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", text)


def test_the_skill_says_what_a_record_proves(skill: str) -> None:
    assert "**What a record proves.**" in skill
    assert "seals each status it writes" in skill
    assert "neither is compared with HEAD" in skill
    assert "a keyless hash, not a signature" in skill


def test_the_skill_names_verify_for_the_work_still_being_there(skill: str) -> None:
    assert "`PLAN verify <id>`" in skill
    assert "reruns the COMPLETE items' tests at HEAD, writes nothing" in skill


def test_the_skill_records_staged_lane_work(skill: str) -> None:
    assert "`PLAN record <id> <ITEM> --staged`" in skill


def test_a_broken_seal_is_repaired_by_record(skill: str) -> None:
    assert "`record` never refuses because another item, or the item itself, fails `check`" in skill


def test_the_commit_ancestry_rule_is_gone(skill: str) -> None:
    assert "commit reachable from HEAD" not in skill
    assert "without the commit and tree `record` writes" not in skill
    assert "`record` waits until the developer commits the staged work" not in skill
