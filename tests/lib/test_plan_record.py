"""``harness_lib.plan_record``: what ``check`` asks of every item a ``record`` call moved.

No git runs here: a record proves that ``record`` wrote it through its seal, so the rules are decided by the
plan alone. A legacy item (recorded before the seal existed) passes only on a plan frozen without a record
scheme.
"""
from __future__ import annotations

from typing import List, Optional

from harness_lib import plan_record as prc
from harness_lib.plan_enums import ItemStatus, OutcomeKind, RecordScheme, RecordSource
from harness_lib.plan_models import (ActionItem, ActionPlan, Blocked, Completed, Frozen, PassedTests,
                                     PlannedTest, Provenance)

COMMIT = "a" * 40
TREE = "b" * 40
DATE = "2026-11-05"
LEGACY_REFS = [COMMIT, f"tree {TREE}", "python -m pytest -q tests/test_calc_sub.py::test_sub"]


def _item(item_id: str = "TASK-1", deps: Optional[List[str]] = None) -> ActionItem:
    return ActionItem(id=item_id, title=f"Item {item_id}", action="Do it.", status=ItemStatus.PENDING,
                      evidence="not started", files=["src/calc.py"], dependencies=deps,
                      tests=[PlannedTest(node="tests/test_calc_sub.py::test_sub", red="ImportError")])


def _plan(*items: ActionItem, scheme: Optional[RecordScheme] = RecordScheme.sealed) -> ActionPlan:
    frozen = Frozen(commit=COMMIT, tree=TREE, date=DATE, digest="e" * 64, records=scheme)
    return ActionPlan(plan_id="0001", plan_created=DATE, execution_model="serial", base_commit=COMMIT,
                      frozen=frozen, items=list(items) or [_item()])


def _completed() -> Completed:
    return Completed(kind=OutcomeKind.complete,
                     provenance=Provenance(source=RecordSource.commit, tree=TREE, commit=COMMIT),
                     tests=PassedTests(nodes=["tests/test_calc_sub.py::test_sub"],
                                       command="python -m pytest -q"))


def _legacy_complete(item_id: str = "TASK-1") -> ActionItem:
    item = _item(item_id)
    item.status, item.evidence, item.verification_references = (
        ItemStatus.COMPLETE, "commit aaaaaaa: 1 test node(s) passed", list(LEGACY_REFS))
    return item


def test_a_stamped_item_has_no_record_problem() -> None:
    plan = _plan()
    prc.stamp(plan, plan.items[0], _completed(), DATE)
    item = plan.items[0]
    assert item.status == ItemStatus.COMPLETE and item.evidence.startswith("commit aaaaaaa")
    assert prc.record_problems(plan) == []


def test_a_pending_plan_has_no_record_problem() -> None:
    assert prc.record_problems(_plan()) == []


def test_a_hand_set_status_is_a_missing_record() -> None:
    plan = _plan()
    plan.items[0].status = ItemStatus.COMPLETE
    [problem] = prc.record_problems(plan)
    assert problem.item == "TASK-1" and problem.kind == prc.RecordProblemKind.missing
    assert str(problem) == ("TASK-1 is COMPLETE without a sealed record; "
                            "run plan.py record 0001 TASK-1")


def test_a_hand_edit_after_the_stamp_is_a_seal_problem() -> None:
    plan = _plan()
    prc.stamp(plan, plan.items[0], _completed(), DATE)
    plan.items[0].evidence = "commit 1234567: 9 test node(s) passed"
    [problem] = prc.record_problems(plan)
    assert problem.kind == prc.RecordProblemKind.seal
    assert "TASK-1 record does not match its seal" in str(problem)
    assert "run plan.py record 0001 TASK-1 again" in str(problem)


def test_a_record_copied_to_another_item_is_a_seal_problem() -> None:
    plan = _plan(_item("TASK-1"), _item("TASK-2"))
    prc.stamp(plan, plan.items[0], _completed(), DATE)
    plan.items[1].status = plan.items[0].status
    plan.items[1].evidence = plan.items[0].evidence
    plan.items[1].record = plan.items[0].record.model_copy(deep=True)
    assert [(p.item, p.kind) for p in prc.record_problems(plan)] == [("TASK-2", prc.RecordProblemKind.seal)]


def test_a_record_left_on_a_pending_item_is_a_seal_problem() -> None:
    plan = _plan()
    prc.stamp(plan, plan.items[0], _completed(), DATE)
    plan.items[0].status = ItemStatus.PENDING
    assert [p.kind for p in prc.record_problems(plan)] == [prc.RecordProblemKind.seal]


def test_legacy_shapes_pass_only_without_a_record_scheme() -> None:
    complete, blocked = _item("TASK-1"), _item("TASK-2")
    complete.status, complete.evidence, complete.verification_references = (
        ItemStatus.COMPLETE, "commit aaaaaaa: 1 test node(s) passed", list(LEGACY_REFS))
    blocked.status, blocked.evidence = ItemStatus.BLOCKED, "waits on the operator module"
    assert prc.record_problems(_plan(complete, blocked, scheme=None)) == []
    sealed = _plan(complete.model_copy(deep=True), blocked.model_copy(deep=True))
    assert [p.item for p in prc.record_problems(sealed)] == ["TASK-1", "TASK-2"]


def test_a_legacy_complete_item_needs_both_references() -> None:
    item = _item()
    item.status, item.evidence, item.verification_references = ItemStatus.COMPLETE, "done", [COMMIT]
    assert [p.kind for p in prc.record_problems(_plan(item, scheme=None))] == [prc.RecordProblemKind.missing]


def test_an_unfrozen_plan_accepts_no_legacy_shape() -> None:
    item = _item()
    item.status, item.evidence, item.verification_references = (
        ItemStatus.COMPLETE, "done", list(LEGACY_REFS))
    plan = _plan(item)
    plan.frozen = None
    assert [p.item for p in prc.record_problems(plan)] == ["TASK-1"]


def test_the_scheme_is_sealed_once_no_legacy_item_remains() -> None:
    legacy = _item()
    legacy.status, legacy.evidence, legacy.verification_references = (
        ItemStatus.COMPLETE, "done", list(LEGACY_REFS))
    plan = _plan(legacy, _item("TASK-2"), scheme=None)
    assert prc.scheme_for(plan) is None
    prc.stamp(plan, plan.items[0], _completed(), DATE)
    assert prc.scheme_for(plan) == RecordScheme.sealed


def test_stamp_clears_the_legacy_references() -> None:
    item = _item()
    item.verification_references = list(LEGACY_REFS)
    plan = _plan(item)
    prc.stamp(plan, item, Blocked(kind=OutcomeKind.blocked, reason="waits"), DATE)
    assert item.verification_references == [] and item.status == ItemStatus.BLOCKED
    assert item.evidence == "waits"


def test_a_dependency_counts_only_with_a_valid_record() -> None:
    upstream = _item("TASK-1")
    plan = _plan(upstream, _item("TASK-2", deps=["TASK-1"]))
    upstream.status = ItemStatus.COMPLETE
    assert not prc.record_holds(plan, upstream)
    prc.stamp(plan, upstream, _completed(), DATE)
    assert prc.record_holds(plan, upstream)


def test_a_legacy_dependency_counts_only_on_a_legacy_plan() -> None:
    legacy = _plan(_legacy_complete(), _item("TASK-2", deps=["TASK-1"]), scheme=None)
    assert prc.record_holds(legacy, legacy.items[0])
    sealed = _plan(_legacy_complete(), _item("TASK-2", deps=["TASK-1"]))
    assert not prc.record_holds(sealed, sealed.items[0])


def test_on_a_legacy_plan_an_item_with_a_record_is_judged_by_its_seal() -> None:
    plan = _plan(scheme=None)
    prc.stamp(plan, plan.items[0], Blocked(kind=OutcomeKind.blocked, reason="waits"), DATE)
    plan.items[0].evidence = "no longer waits"
    assert [p.kind for p in prc.record_problems(plan)] == [prc.RecordProblemKind.seal]
    assert not prc.record_holds(plan, plan.items[0])


def test_the_freeze_digest_folds_in_only_a_set_record_scheme() -> None:
    from harness_lib import plan_doc as pd
    plan = _plan()
    assert pd.frozen_digest(plan) == pd.frozen_digest(plan, None)
    assert pd.frozen_digest(plan, RecordScheme.sealed) != pd.frozen_digest(plan)
