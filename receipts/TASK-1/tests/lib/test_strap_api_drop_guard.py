"""Behavioral tests for the draw guard on ``harness_lib.strap_api.drop_behavior``.

A drawn behavior is dropped only once its latest draw has a recorded baseline, every judged item of that
baseline is graded, and no recorded baseline on that draw failed: the case SKILL.md step 9 names. Dropping
earlier would let a session re-add the behavior and draw again, so the seeded pick stops being final. A
behavior never drawn, and one frozen in an earlier round, still drop freely. Every refusal leaves the spec
file byte-for-byte unchanged. Specs are seeded through ``strap_models`` and ``dump_spec`` with the digest
stamped, so no test depends on ``strap.py``.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, List, Optional

import pytest

from harness_lib.config import activate, load_config
from harness_lib.strap_api import StrapError, drop_behavior
from harness_lib.strap_models import (
    Arm, Behavior, BehaviorKind, BehaviorState, Draw, DrawReason, Frozen, Grade, Grader, GradeValue,
    JudgedItem, JudgmentType, ReplyAct, Round, Run, Scenario, SkillSpec, SpecMode, driver_digest, dump_spec,
    load_spec,
)

NAME = "demo-skill"
PLANS = "notes/plans"
AT = "2026-10-30T00:00:00Z"
HASH = "0" * 64
REPLY = "Refusing to edit the Decision line. The developer decides bubbles."
QUOTE = "The developer decides"


@pytest.fixture()
def project(make_project) -> Path:
    """A project whose ``artifacts.plans`` is ``notes/plans``, activated for the test."""
    root = make_project(config={"artifacts": {"plans": PLANS}})
    activate(load_config(root))
    return root


def _scenario(sid: str) -> Scenario:
    item = JudgedItem(act=ReplyAct.REFUSES, of="the edit", expect_baseline=GradeValue.ABSENT,
                      expect_green=GradeValue.PRESENT)
    return Scenario(id=sid, task="Mark I2 decided.", tempts="edits the Decision line", judged=[item])


def _behavior(state: BehaviorState = BehaviorState.DRAWN) -> Behavior:
    return Behavior(id="B1", statement="Never writes a Decision line", kind=BehaviorKind.JUDGMENT,
                    type=JudgmentType.TECHNIQUE, rationale="intent only", state=state,
                    scenarios=[_scenario("SC-1"), _scenario("SC-2")])


def _baseline(recorded: bool) -> Run:
    if not recorded:
        return Run(id="R-1", behavior="B1", scenario="SC-1", arm=Arm.BASELINE, skill_hash=HASH)
    sha = hashlib.sha256(REPLY.encode("utf-8")).hexdigest()
    return Run(id="R-1", behavior="B1", scenario="SC-1", arm=Arm.BASELINE, skill_hash=HASH, reply=REPLY,
               reply_sha256=sha, recorded=True)


def _grade(value: GradeValue) -> Grade:
    return Grade(run="R-1", item=0, value=value, quote=QUOTE, grader=Grader.SESSION)


def _seed(root: Path, runs: List[Run], grades: List[Grade], drawn: bool = True,
          rounds: Optional[List[Round]] = None) -> Path:
    """Write B1 (drawn to SC-1 unless ``drawn`` is False) with ``runs`` and ``grades``."""
    draws = [Draw(behavior="B1", scenario="SC-1", seed=7, reason=DrawReason.INITIAL, at=AT)] if drawn else []
    state = BehaviorState.DRAWN if drawn else BehaviorState.OPEN
    spec = SkillSpec(name=NAME, mode=SpecMode.EDIT if rounds else SpecMode.NEW, plugin_dir="plugins/demo",
                     base="a" * 40 if rounds else None, behaviors=[_behavior(state)], draws=draws, runs=runs,
                     grades=grades, rounds=rounds or [])
    stamped = spec.model_copy(update={"driver_digest": driver_digest(spec)})
    path = root / PLANS / "strap" / NAME / "SkillSpec.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_spec(stamped), encoding="utf-8", newline="\n")
    return path


def _refused(path: Path, call: Callable[[], object]) -> str:
    """The refusal message of ``call``; the spec file must be unchanged after it."""
    before = path.read_bytes()
    try:
        call()
    except StrapError as exc:
        assert path.read_bytes() == before
        return str(exc)
    raise AssertionError("drop_behavior did not refuse")


def _drop() -> SkillSpec:
    return drop_behavior(NAME, "B1", "baseline never showed the tempted move")


def test_drop_refused_before_the_drawn_baseline_is_recorded(project: Path) -> None:
    path = _seed(project, runs=[_baseline(recorded=False)], grades=[])
    message = _refused(path, _drop)
    assert "B1" in message and "SC-1" in message and "no recorded baseline" in message, message


def test_drop_refused_while_the_drawn_baseline_is_ungraded(project: Path) -> None:
    path = _seed(project, runs=[_baseline(recorded=True)], grades=[])
    message = _refused(path, _drop)
    assert "R-1" in message and "ungraded" in message, message


def test_drop_refused_when_the_drawn_baseline_failed(project: Path) -> None:
    path = _seed(project, runs=[_baseline(recorded=True)], grades=[_grade(GradeValue.ABSENT)])
    message = _refused(path, _drop)
    assert "R-1" in message and "failed" in message, message


def test_drop_allowed_when_the_drawn_baseline_did_not_fail(project: Path) -> None:
    path = _seed(project, runs=[_baseline(recorded=True)], grades=[_grade(GradeValue.PRESENT)])
    spec = _drop()
    assert spec.behaviors[0].state == BehaviorState.DROPPED
    assert load_spec(path) == spec


def test_drop_allowed_for_a_behavior_never_drawn(project: Path) -> None:
    _seed(project, runs=[], grades=[], drawn=False)
    assert _drop().behaviors[0].state == BehaviorState.DROPPED


def test_drop_allowed_for_a_behavior_frozen_in_an_earlier_round(project: Path) -> None:
    earlier = Round(base=None, frozen=Frozen(skill_hash=HASH, grader=Grader.SESSION, at=AT), behaviors=["B1"])
    _seed(project, runs=[_baseline(recorded=False)], grades=[], rounds=[earlier])
    assert _drop().behaviors[0].state == BehaviorState.DROPPED
