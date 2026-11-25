"""The record models of an ActionPlan item: provenance, the passed tests, one class per outcome, the seal.

Each concept is its own closed class. ``ItemRecord`` owns the seal: ``ItemRecord.sealed`` stamps it over the
item fields it vouches for, and ``holds`` recomputes it, so a hand edit of any covered field shows.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

import pytest
from pydantic import ValidationError

from harness_lib import plan_doc
from harness_lib import plan_models as pm
from harness_lib.plan_enums import ItemStatus, OutcomeKind, RecordScheme, RecordSource
from harness_lib.plan_models import (ActionItem, Blocked, Closed, Completed, ItemRecord, PassedTests,
                                     PlannedTest, Provenance, SealedFields, Started)

COMMIT = "a" * 40
TREE = "b" * 40
DATE = "2026-11-05"
NODE = "tests/test_calc_sub.py::test_sub"


def _completed() -> Completed:
    provenance = Provenance(source=RecordSource.commit, tree=TREE, commit=COMMIT)
    return Completed(kind=OutcomeKind.complete, provenance=provenance,
                     tests=PassedTests(nodes=[NODE], command=f"python -m pytest -q {NODE}"))


def _item(outcome: Any = None) -> ActionItem:
    """An item carrying ``outcome`` the way ``plan.py record`` leaves it: status, evidence, sealed record."""
    outcome = outcome or _completed()
    item = ActionItem(id="TASK-1", title="Add subtraction", action="Add sub.", status=ItemStatus.PENDING,
                      evidence="not started", files=["src/calc.py"],
                      tests=[PlannedTest(node=NODE, red="ImportError")])
    item.status = outcome.status
    item.evidence = outcome.evidence(DATE)
    item.record = ItemRecord.sealed("0001", item, outcome, DATE)
    return item


# --- provenance -------------------------------------------------------------------------------------------

def test_a_commit_provenance_needs_its_commit() -> None:
    with pytest.raises(ValidationError):
        Provenance(source=RecordSource.commit, tree=TREE)


def test_a_staged_provenance_carries_no_commit() -> None:
    with pytest.raises(ValidationError):
        Provenance(source=RecordSource.staged, tree=TREE, commit=COMMIT)
    assert Provenance(source=RecordSource.staged, tree=TREE).commit is None


def test_provenance_rejects_a_short_tree() -> None:
    with pytest.raises(ValidationError):
        Provenance(source=RecordSource.staged, tree="b" * 7)


# --- outcomes ---------------------------------------------------------------------------------------------

def test_each_outcome_names_the_status_it_implies() -> None:
    assert _completed().status == ItemStatus.COMPLETE
    assert Started(kind=OutcomeKind.started).status == ItemStatus.IN_PROGRESS
    assert Blocked(kind=OutcomeKind.blocked, reason="waits").status == ItemStatus.BLOCKED
    assert Closed(kind=OutcomeKind.closed, rationale="superseded").status == ItemStatus.CLOSED_NO_ACTION


def test_the_kind_selects_the_outcome_class() -> None:
    record = ItemRecord.model_validate({"outcome": {"kind": "blocked", "reason": "waits"}, "date": DATE,
                                        "seal": "c" * 64})
    assert isinstance(record.outcome, Blocked) and record.outcome.reason == "waits"
    with pytest.raises(ValidationError):
        ItemRecord.model_validate({"outcome": {"kind": "done"}, "date": DATE, "seal": "c" * 64})


def test_a_blocked_or_closed_outcome_needs_its_text() -> None:
    with pytest.raises(ValidationError):
        Blocked(kind=OutcomeKind.blocked, reason="")
    with pytest.raises(ValidationError):
        Closed(kind=OutcomeKind.closed, rationale="")


def test_passed_tests_need_a_node() -> None:
    with pytest.raises(ValidationError):
        PassedTests(nodes=[], command="python -m pytest -q")


def test_evidence_names_the_commit_or_the_staged_tree() -> None:
    assert _completed().evidence(DATE) == f"commit {COMMIT[:7]}: 1 test node(s) passed"
    staged = Completed(kind=OutcomeKind.complete,
                       provenance=Provenance(source=RecordSource.staged, tree=TREE))
    assert staged.evidence(DATE) == f"staged tree {TREE[:7]}"
    assert Started(kind=OutcomeKind.started).evidence(DATE) == f"started {DATE}"
    assert Closed(kind=OutcomeKind.closed, rationale="superseded").evidence(DATE) == "superseded"


# --- the seal ---------------------------------------------------------------------------------------------

def test_a_sealed_record_holds_for_its_item() -> None:
    item = _item()
    assert item.record is not None and item.record.holds("0001", item)


def test_every_outcome_seals() -> None:
    for outcome in (Started(kind=OutcomeKind.started), Blocked(kind=OutcomeKind.blocked, reason="waits"),
                    Closed(kind=OutcomeKind.closed, rationale="superseded")):
        item = _item(outcome)
        assert item.status == outcome.status and item.record.holds("0001", item)


EDITS: Dict[str, Callable[[ActionItem], None]] = {
    "status": lambda i: setattr(i, "status", ItemStatus.CLOSED_NO_ACTION),
    "evidence": lambda i: setattr(i, "evidence", "commit 1234567: 3 test node(s) passed"),
    "files": lambda i: i.files.append("src/extra.py"),
    "tests": lambda i: i.tests.append(PlannedTest(node="tests/test_calc_sub.py::test_more",
                                                  red="ImportError")),
    "id": lambda i: setattr(i, "id", "TASK-2"),
    "record date": lambda i: setattr(i.record, "date", "2026-11-06"),
    "record tree": lambda i: setattr(i.record.outcome.provenance, "tree", "d" * 40),
}


@pytest.mark.parametrize("field", sorted(EDITS))
def test_the_seal_breaks_when_a_covered_field_changes(field: str) -> None:
    item = _item()
    EDITS[field](item)
    assert not item.record.holds("0001", item)


def test_the_seal_binds_the_plan_id() -> None:
    item = _item()
    assert not item.record.holds("0002", item)


def test_the_seal_ignores_fields_outside_the_record() -> None:
    item = _item()
    item.notes = "a later note"
    item.model = "opus"
    assert item.record.holds("0001", item)


def test_the_sealed_fields_are_a_model_whose_digest_is_the_seal() -> None:
    item = _item()
    fields = SealedFields.of("0001", item, item.record.outcome, item.record.date)
    assert fields.id == "TASK-1" and fields.status == ItemStatus.COMPLETE
    assert fields.digest() == item.record.seal and len(fields.digest()) == 64


def test_a_record_reseals_after_a_round_trip_through_the_plan_file() -> None:
    item = _item()
    plan = pm.ActionPlan(plan_id="0001", plan_created=DATE, execution_model="serial", items=[item])
    loaded = pm.ActionPlan.model_validate(json.loads(json.dumps(plan_doc.plan_dict(plan))))
    assert loaded.items[0].record.holds("0001", loaded.items[0])


class _LaterPlannedTest(PlannedTest):
    """A PlannedTest as a later release might ship it: one more field, defaulted."""

    note: Optional[str] = None


class _LaterSealedFields(SealedFields):
    """The sealed payload of a later release whose PlannedTest carries the extra defaulted field."""

    tests: List[_LaterPlannedTest]


def test_a_defaulted_field_added_later_keeps_the_seal() -> None:
    item = _item()
    fields = SealedFields.of("0001", item, item.record.outcome, item.record.date)
    later = _LaterSealedFields.model_validate(
        {**fields.model_dump(), "tests": [_LaterPlannedTest(node=NODE, red="ImportError")]})
    assert later.digest() == item.record.seal


# --- placement --------------------------------------------------------------------------------------------

def test_record_is_a_mutable_item_field() -> None:
    assert "record" in pm.mutable_item()


def test_frozen_carries_the_record_scheme() -> None:
    frozen = pm.Frozen(commit=COMMIT, tree=TREE, date=DATE, digest="e" * 64, records=RecordScheme.sealed)
    assert frozen.records == RecordScheme.sealed
    assert pm.Frozen(commit=COMMIT, tree=TREE, date=DATE, digest="e" * 64).records is None


def test_the_record_models_are_closed() -> None:
    for model in (Provenance, PassedTests, Completed, Started, Blocked, Closed, ItemRecord, SealedFields):
        assert model.model_config["extra"] == "forbid", model.__name__


def test_the_generated_schema_names_the_record_models() -> None:
    text = pm.schema_text()
    assert all(name in text for name in ("ItemRecord", "Provenance", "PassedTests", "Completed"))
