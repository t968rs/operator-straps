"""Receipts: one sealed record per plan item, kept outside the frozen plan.

The seal covers every receipt field but itself, plus the item's planned files and tests as frozen, so a hand
edit, a receipt copied to another item or plan, or a refreeze that moves the item's files or tests breaks it.
Deviations (an extra file, a substituted test node) each cite a DesignChange id.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest
from pydantic import ValidationError

from harness_lib.plan_enums import ItemStatus, OutcomeKind, RecordScheme, RecordSource
from harness_lib.plan_models import ActionItem, Blocked, Completed, PassedTests, PrAttributes, Provenance
from harness_lib.receipt_models import Deviations, ExtraFile, Receipt, TestSubstitution

TREE, COMMIT = "b" * 40, "c" * 40
NODE = "tests/test_calc_sub.py::test_sub"
OTHER = "tests/test_calc_minus.py::test_minus"
DIGEST = "a" * 64


def item(**over: Any) -> ActionItem:
    raw: Dict[str, Any] = {"id": "TASK-1", "title": "Add sub", "action": "Add sub.", "status": "PENDING",
                           "evidence": "not started", "files": ["src/calc.py"],
                           "tests": [{"node": NODE, "red": "ImportError"}]}
    raw.update(over)
    return ActionItem.model_validate(raw)


def done(nodes: Any = (NODE,)) -> Completed:
    prov = Provenance(source=RecordSource.commit, tree=TREE, commit=COMMIT)
    return Completed.of(prov, PassedTests.of(list(nodes), ["python", "-m", "pytest", *nodes]))


def deviations() -> Deviations:
    return Deviations(extra_files=[ExtraFile(path="src/helper.py", change="EX1")],
                      substitutions=[TestSubstitution(planned=NODE, node=OTHER, change="EX1")],
                      change_digests={"EX1": DIGEST})


def sealed(**over: Any) -> Receipt:
    args: Dict[str, Any] = {"outcome": done(), "date": "2026-11-10"}
    args.update(over)
    return Receipt.sealed("0001", item(), **args)


def test_the_record_scheme_has_receipts() -> None:
    assert RecordScheme("receipts") == RecordScheme.receipts


def test_a_pip_document_may_be_html() -> None:
    attrs = PrAttributes(pr=1, branch="feat-x", base_branch="main",
                         pip_document="docs/PLANS/0001_Add_operators_PIP.html")
    assert attrs.pip_document.endswith(".html")


def test_a_sealed_receipt_holds_for_its_item() -> None:
    receipt = sealed()
    assert receipt.holds("0001", item())
    assert receipt.status == ItemStatus.COMPLETE and receipt.evidence.startswith("commit ccccccc")


def test_every_outcome_seals() -> None:
    receipt = sealed(outcome=Blocked(kind=OutcomeKind.blocked, reason="waits on the operator module"))
    assert receipt.holds("0001", item()) and receipt.status == ItemStatus.BLOCKED


@pytest.mark.parametrize("field, value", [
    ("evidence", "commit aaaaaaa: 9 test node(s) passed"),
    ("date", "2026-11-11"),
    ("ref", "v1"),
    ("deviations", Deviations(extra_files=[ExtraFile(path="src/other.py", change="EX1")],
                              change_digests={"EX1": DIGEST})),
])
def test_the_seal_breaks_when_a_receipt_field_changes(field: str, value: Any) -> None:
    receipt = sealed().model_copy(update={field: value})
    assert not receipt.holds("0001", item())


def test_the_seal_breaks_when_the_items_planned_files_change() -> None:
    assert not sealed().holds("0001", item(files=["src/calc.py", "src/more.py"]))


def test_the_seal_breaks_when_the_items_planned_tests_change() -> None:
    assert not sealed().holds("0001", item(tests=[{"node": OTHER, "red": "ImportError"}]))


def test_the_seal_binds_the_plan_and_the_item() -> None:
    receipt = sealed()
    assert not receipt.holds("0002", item())
    assert not receipt.holds("0001", item(id="TASK-2"))


def test_the_seal_ignores_item_fields_outside_files_and_tests() -> None:
    assert sealed().holds("0001", item(title="Add subtraction", action="Add sub beside add."))


def test_deviations_and_ref_are_sealed_and_kept() -> None:
    receipt = sealed(outcome=done((OTHER,)), deviations=deviations(), ref="v1")
    assert receipt.holds("0001", item()) and receipt.ref == "v1"
    assert receipt.deviations.cited == ["EX1"]


def test_the_nodes_of_a_receipt_apply_its_substitutions() -> None:
    receipt = sealed(outcome=done((OTHER,)), deviations=deviations())
    assert receipt.nodes(item()) == [OTHER]
    assert sealed().nodes(item()) == [NODE]


def test_a_receipt_round_trips_through_json() -> None:
    receipt = sealed(deviations=deviations())
    again = Receipt.model_validate_json(receipt.model_dump_json())
    assert again == receipt and again.holds("0001", item())


@pytest.mark.parametrize("model", [ExtraFile, TestSubstitution, Deviations, Receipt])
def test_the_receipt_models_are_closed(model: type) -> None:
    assert model.model_config.get("extra") == "forbid"


def test_a_substitution_names_a_pytest_node() -> None:
    with pytest.raises(ValidationError):
        TestSubstitution(planned=NODE, node="tests/test_calc_minus.py", change="EX1")


def test_pytest_does_not_collect_the_substitution_model() -> None:
    assert TestSubstitution.__test__ is False


def test_deviations_bind_the_digest_of_each_cited_change() -> None:
    receipt = sealed(outcome=done((OTHER,)), deviations=deviations())
    assert receipt.deviations.change_digests == {"EX1": DIGEST} and receipt.holds("0001", item())
    moved = deviations().model_copy(update={"change_digests": {"EX1": "0" * 64}})
    assert not receipt.model_copy(update={"deviations": moved}).holds("0001", item())


def test_deviations_refuse_a_citation_without_its_digest() -> None:
    with pytest.raises(ValidationError, match="EX2"):
        Deviations(extra_files=[ExtraFile(path="src/helper.py", change="EX2")], change_digests={"EX1": DIGEST})
