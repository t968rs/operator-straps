"""The PIP shows an item's sealed record (provenance and the passed tests) and still shows legacy
references."""
from __future__ import annotations

from harness_lib import plan_record as prc
from harness_lib.plan_enums import ItemStatus, OutcomeKind, RecordSource
from harness_lib.plan_models import (ActionItem, ActionPlan, Completed, PassedTests, PlannedTest,
                                     Provenance)
from harness_lib.plan_render import render_pip

COMMIT = "a1b2c3d" + "a" * 33
TREE = "e4f5a6b" + "b" * 33
NODE = "tests/test_calc_sub.py::test_sub"


def _plan() -> ActionPlan:
    item = ActionItem(id="TASK-1", title="Add subtraction", action="Add sub.", status=ItemStatus.PENDING,
                      evidence="not started", files=["src/calc.py"],
                      tests=[PlannedTest(node=NODE, red="ImportError")])
    return ActionPlan(plan_id="0001", plan_created="2026-11-05", execution_model="serial", items=[item])


def _stamp(plan: ActionPlan, provenance: Provenance) -> None:
    outcome = Completed(kind=OutcomeKind.complete, provenance=provenance,
                        tests=PassedTests(nodes=[NODE], command=f"python -m pytest -q {NODE}"))
    prc.stamp(plan, plan.items[0], outcome, "2026-11-05")


def test_a_commit_record_renders_its_commit_tree_and_command() -> None:
    plan = _plan()
    _stamp(plan, Provenance(source=RecordSource.commit, tree=TREE, commit=COMMIT))
    pip = render_pip(plan, "0001_Add_subtraction_ActionPlan.json")
    assert "**Recorded:** 2026-11-05, commit `a1b2c3d`, tree `e4f5a6b`" in pip
    assert f"- `python -m pytest -q {NODE}`" in pip


def test_a_staged_record_renders_the_index_tree() -> None:
    plan = _plan()
    _stamp(plan, Provenance(source=RecordSource.staged, tree=TREE))
    pip = render_pip(plan, "0001_Add_subtraction_ActionPlan.json")
    assert "**Recorded:** 2026-11-05, staged, tree `e4f5a6b`" in pip


def test_the_record_box_names_both_ways_to_record() -> None:
    pip = render_pip(_plan(), "0001_Add_subtraction_ActionPlan.json")
    assert "- [ ] Record it: `plan.py record 0001 TASK-1 --sha <sha>` or `--staged`" in pip


def test_legacy_references_still_render() -> None:
    plan = _plan()
    item = plan.items[0]
    item.status, item.evidence = ItemStatus.COMPLETE, "commit a1b2c3d: 1 test node(s) passed"
    item.verification_references = [COMMIT, f"tree {TREE}"]
    pip = render_pip(plan, "0001_Add_subtraction_ActionPlan.json")
    assert f"- `{COMMIT}`" in pip and f"- `tree {TREE}`" in pip and "**Recorded:**" not in pip
