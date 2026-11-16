"""A decision id used twice is a plan problem (plan 1020, TASK-5).

The HTML PIP anchors each decision block at ``id="decision-<id>"``, so two decisions with one id would put
two elements with one id on the page. ``plan_checks.decision_problems`` reports the repeat the way
``duplicate_problems`` reports a repeated item id.
"""
from __future__ import annotations

from typing import Any, Dict

from harness_lib import plan_checks as pc
from harness_lib.plan_doc import validate_plan
from harness_lib.plan_models import ActionPlan

WALK_ROOTS = ()


def decision(ident: str, first: str, second: str) -> Dict[str, Any]:
    return {"id": ident, "question": "Which?", "chosen": first,
            "options": [{"id": first, "summary": "one"}, {"id": second, "summary": "two"}]}


def plan(*decisions: Dict[str, Any]) -> ActionPlan:
    item = {"id": "TASK-1", "title": "t", "action": "a", "status": "PENDING", "evidence": "e"}
    return validate_plan({"plan_id": "0001", "plan_created": "2026-11-16", "execution_model": "serial",
                          "items": [item], "decisions": list(decisions)})


def test_a_decision_id_used_twice_is_a_problem() -> None:
    twice = plan(decision("D1", "split", "keep"), decision("D1", "merge", "drop"))
    assert pc.decision_problems(twice) == ["decision id D1 is used 2 times"]


def test_distinct_decision_ids_are_not_a_problem() -> None:
    assert pc.decision_problems(plan(decision("D1", "split", "keep"), decision("D2", "merge", "drop"))) == []
