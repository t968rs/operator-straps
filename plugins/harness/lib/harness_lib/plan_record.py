"""The record rules of an ActionPlan: what ``check`` asks of every item a ``record`` call moved.

No git runs here. A sealed record proves that ``plan.py record`` wrote it, so every rule is decided by the
plan alone. An item that carries a record is judged by its seal; one without a record passes only as a legacy
shape on a plan frozen without a record scheme. Known limits, accepted like a recomputed hash: copying an
item's own earlier record back by hand passes the seal, and ``keeps_sealed`` sees a hand-deleted scheme
only while the digest still matches under it. A refreeze (``plan.py freeze``) also keeps the scheme the
plan's copy at HEAD stores, so only a deleted scheme that was never committed lets a refreeze judge the
plan as legacy.
"""
from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from harness_lib.plan_doc import frozen_digest
from harness_lib.plan_enums import ItemStatus, RecordProblemKind, RecordScheme, VerifyKind
from harness_lib.plan_models import ActionItem, ActionPlan, Completed, Outcome

_COMMIT_REF = re.compile(r"[0-9a-f]{40}")
_TREE_REF = re.compile(r"tree [0-9a-f]{40}")
_ALL_FLAGS = "--sha SHA | --staged | --start | --blocked REASON | --closed RATIONALE"
_STATUS_FLAGS = {
    ItemStatus.COMPLETE: "--sha SHA | --staged",
    ItemStatus.IN_PROGRESS: "--start",
    ItemStatus.BLOCKED: "--blocked REASON",
    ItemStatus.CLOSED_NO_ACTION: "--closed RATIONALE",
}


def record_command(plan_id: str, item_id: str, status: Optional[ItemStatus] = None,
                   again: bool = False) -> str:
    """The instruction that repairs an item's record, with the mode flags ``record`` requires.

    ``status`` narrows the flags to the ones that record that status; PENDING or None lists every mode.
    """
    flags = _ALL_FLAGS if status is None else _STATUS_FLAGS.get(status, _ALL_FLAGS)
    word = " again" if again else ""
    return f"run plan.py record {plan_id} {item_id}{word} ({flags})"


class RecordProblem(BaseModel):
    """One item that fails the record rules; ``str()`` is the line ``check`` prints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str
    item: str
    status: ItemStatus
    kind: RecordProblemKind

    def __str__(self) -> str:
        again = self.kind != RecordProblemKind.missing
        command = record_command(self.plan_id, self.item, self.status, again=again)
        if not again:
            return f"{self.item} is {self.status} without a sealed record; {command}"
        return (f"{self.item} record does not match its seal (status, evidence, files, tests or the record "
                f"changed by hand); {command}")


def legacy_allowed(plan: ActionPlan) -> bool:
    """The plan was frozen without a record scheme, so legacy item shapes still pass."""
    return plan.frozen is not None and plan.frozen.records is None


def legacy_shape(item: ActionItem) -> bool:
    """A pre-seal record: COMPLETE with a commit and a tree reference, any other non-PENDING with evidence."""
    if item.status == ItemStatus.COMPLETE:
        refs = item.verification_references
        return (len(refs) >= 2 and _COMMIT_REF.fullmatch(refs[0]) is not None
                and _TREE_REF.fullmatch(refs[1]) is not None)
    return item.status != ItemStatus.PENDING and bool(item.evidence.strip())


def _problem(plan: ActionPlan, item: ActionItem) -> Optional[RecordProblem]:
    """The record problem of one item; None for a PENDING item without a record or a proven status."""
    if (item.record is None and item.status == ItemStatus.PENDING) or record_holds(plan, item):
        return None
    kind = RecordProblemKind.missing if item.record is None else RecordProblemKind.seal
    return RecordProblem(plan_id=plan.plan_id, item=item.id, status=item.status, kind=kind)


def record_problems(plan: ActionPlan) -> List[RecordProblem]:
    """One problem per item with a record or a non-PENDING status that fails the record rules."""
    return [problem for item in plan.items if (problem := _problem(plan, item)) is not None]


def record_lines(plan: ActionPlan) -> List[str]:
    """``record_problems`` as the lines ``check`` prints."""
    return [str(problem) for problem in record_problems(plan)]


def record_holds(plan: ActionPlan, item: ActionItem) -> bool:
    """The item's status is proven: by its sealed record, or by a legacy shape on a legacy plan."""
    if item.record is not None:
        return item.record.holds(plan.plan_id, item)
    return legacy_allowed(plan) and legacy_shape(item)


def scheme_for(plan: ActionPlan) -> Optional[RecordScheme]:
    """The record scheme a freeze stores: sealed, unless a non-PENDING item still lacks a record."""
    legacy = any(item.status != ItemStatus.PENDING and item.record is None for item in plan.items)
    return None if legacy else RecordScheme.sealed


def keeps_sealed(plan: ActionPlan) -> bool:
    """A frozen plan stays on the sealed scheme: it is stored, or the digest proves a hand deleted it."""
    frozen = plan.frozen
    if frozen is None:
        return False
    sealed = RecordScheme.sealed
    return frozen.records == sealed or frozen.digest == frozen_digest(plan, sealed)


def recorded_nodes(item: ActionItem) -> List[str]:
    """The nodes a COMPLETE record passed; a legacy item without a record falls back to its planned tests."""
    if item.record is None:
        return [test.node for test in item.tests]
    outcome = item.record.outcome
    tests = outcome.tests if isinstance(outcome, Completed) else None
    return list(tests.nodes) if tests is not None else []


class VerifyResult(BaseModel):
    """What ``plan.py verify`` found for one COMPLETE item; ``str()`` is its output line.

    ``detail`` is empty for ``pass`` and ``no_tests``; for ``fail`` it holds the location, the pytest tail
    and the repair, for ``unrecorded`` the repair alone.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    item: str
    kind: VerifyKind
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.kind in (VerifyKind.fail, VerifyKind.unrecorded)

    def __str__(self) -> str:
        if self.kind == VerifyKind.pass_:
            return f"{self.item} pass"
        if self.kind == VerifyKind.no_tests:
            return f"{self.item} no tests"
        if self.kind == VerifyKind.fail:
            return f"{self.item} tests fail at {self.detail}"
        return f"{self.item} is COMPLETE without a valid record to verify; {self.detail}"


def stamp(plan: ActionPlan, item: ActionItem, outcome: Outcome, date: str) -> None:
    """Move ``item`` of ``plan`` to ``outcome`` (``ActionItem.stamp`` under the plan's id)."""
    item.stamp(plan.plan_id, outcome, date)
