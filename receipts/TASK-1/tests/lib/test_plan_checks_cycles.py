"""Checks of ``plan_checks.dependency_problems``: a cycle names its members, not the items behind it."""
from __future__ import annotations

from typing import Dict, List

from harness_lib import plan_checks as pc
from harness_lib.plan_enums import ItemStatus
from harness_lib.plan_models import ActionItem, ActionPlan


def plan(deps: Dict[str, List[str]]) -> ActionPlan:
    """A plan built without validation: the graph tests use single-letter ids the models would reject."""
    items = [ActionItem.model_construct(id=key, title=key, status=ItemStatus.PENDING, dependencies=value)
             for key, value in deps.items()]
    return ActionPlan.model_construct(plan_id="0001", items=items)


def test_an_item_behind_a_cycle_is_not_named_a_member() -> None:
    data = plan({"A": ["B"], "B": ["A"], "C": ["A"]})
    assert pc.dependency_problems(data) == ["dependency cycle among A, B"]


def test_a_self_dependency_is_a_cycle_of_one() -> None:
    assert pc.dependency_problems(plan({"A": ["A"], "B": ["A"]})) == ["dependency cycle among A"]


def test_an_acyclic_chain_has_no_problem() -> None:
    assert pc.dependency_problems(plan({"A": [], "B": ["A"], "C": ["B", "A"]})) == []
