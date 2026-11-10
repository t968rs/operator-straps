"""The execution files of a plan: receipts under ``<plans>/<id>/receipts/`` and the plan's DesignEvolution.

``plan_receipts`` reads and writes receipts, builds the status view (the plan with each item's status taken
from its receipt, in memory only) and lists the receipt problems ``check`` reports: a file that does not
parse, a broken seal, a receipt for no item, a citation of an entry that is missing or does not name the item.
A receipt binds the digest of each change it cites, so a cited change edited later asks for a new record.
``book_for`` gives each command one ``RecordBook`` for the plan's scheme: receipts, or the records in the plan.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from harness_lib import evolution_doc as ed
from harness_lib import plan_receipts as prt
from harness_lib.evolution_models import DesignEvolution
from harness_lib.plan_enums import ItemStatus, RecordSource
from harness_lib.plan_models import ActionPlan, Completed, PassedTests, Provenance
from harness_lib.receipt_models import Deviations, ExtraFile, Receipt

WALK_ROOTS = ()  # walks only tmp_path
NODE = "tests/test_calc_sub.py::test_sub"
FROZEN = {"commit": "a" * 40, "tree": "b" * 40, "date": "2026-11-10", "digest": "d" * 64, "records": "receipts"}


def _item(ident: str) -> Dict[str, Any]:
    return {"id": ident, "title": f"Item {ident}", "action": "Do it.", "status": "PENDING",
            "evidence": "not started", "files": ["src/calc.py"], "tests": [{"node": NODE, "red": "ImportError"}]}


def plan(frozen: Optional[Dict[str, Any]] = FROZEN) -> ActionPlan:
    raw: Dict[str, Any] = {"plan_id": "0001", "plan_created": "2026-11-10", "execution_model": "serial",
                           "base_commit": "e" * 40, "items": [_item("TASK-1"), _item("TASK-2")]}
    if frozen is not None:
        raw["frozen"] = dict(frozen)
    return ActionPlan.model_validate(raw)


def receipt(the_plan: ActionPlan, ident: str = "TASK-1", deviations: Optional[Deviations] = None) -> Receipt:
    prov = Provenance(source=RecordSource.commit, tree="c" * 40, commit="f" * 40)
    outcome = Completed.of(prov, PassedTests.of([NODE], ["python", "-m", "pytest", NODE]))
    target = next(i for i in the_plan.items if i.id == ident)
    return Receipt.sealed(the_plan.plan_id, target, outcome=outcome, date="2026-11-10", deviations=deviations)


def evolution(items: List[str]) -> DesignEvolution:
    return DesignEvolution.model_validate({
        "plan_id": "0001", "feature": "Add operators", "branch_lineage": "main-->feat-x",
        "primary_documents": {"plan": "docs/PLANS/0001_Add_operators_ActionPlan.json"},
        "changes": [{"id": "EX1", "discovered_by": "implementer", "phase": "post-exec-start", "items": items,
                     "original": {"doc": "plan", "location": "TASK-1", "indicated": "src/calc.py"},
                     "issue": {"category": "spec-coverage", "why_categorical": "x", "why_free_form": "y"},
                     "new_outcome": {"doc": "plan", "indicated": "also src/helper.py"},
                     "why_new_outcome": {"category": "execution-blocker", "free_form": "z"},
                     "date": "2026-11-10"}]})


def extra(change: str = "EX1") -> Deviations:
    digest = evolution(["TASK-1"]).changes[0].digest()
    return Deviations(extra_files=[ExtraFile(path="src/helper.py", change=change)], change_digests={change: digest})


def test_a_receipt_lands_under_the_plan_folder_and_loads_back(tmp_path: Path) -> None:
    the_plan = plan()
    path = prt.write_receipt(tmp_path, receipt(the_plan))
    assert path == tmp_path / "0001" / "receipts" / "TASK-1.json"
    loaded = prt.load_receipts(tmp_path, "0001")
    assert loaded.problems == [] and loaded.receipts["TASK-1"] == receipt(the_plan)


def test_no_receipts_folder_is_no_receipts(tmp_path: Path) -> None:
    loaded = prt.load_receipts(tmp_path, "0001")
    assert loaded.receipts == {} and loaded.problems == []


def test_a_receipt_that_does_not_parse_is_a_problem(tmp_path: Path) -> None:
    folder = tmp_path / "0001" / "receipts"
    folder.mkdir(parents=True)
    (folder / "TASK-1.json").write_text("{not json", encoding="utf-8")
    loaded = prt.load_receipts(tmp_path, "0001")
    assert loaded.receipts == {} and any("TASK-1.json" in p for p in loaded.problems)


def test_only_a_receipts_plan_uses_receipts() -> None:
    assert prt.uses_receipts(plan())
    assert not prt.uses_receipts(plan(dict(FROZEN, records="sealed")))
    assert not prt.uses_receipts(plan(None))


def test_the_status_view_reads_receipts_and_leaves_the_plan_alone(tmp_path: Path) -> None:
    the_plan = plan()
    prt.write_receipt(tmp_path, receipt(the_plan))
    view = prt.status_view(the_plan, prt.load_receipts(tmp_path, "0001"))
    assert [i.status for i in view.items] == [ItemStatus.COMPLETE, ItemStatus.PENDING]
    assert view.items[0].evidence.startswith("commit fffffff")
    assert [i.status for i in the_plan.items] == [ItemStatus.PENDING, ItemStatus.PENDING]


def test_a_sound_receipt_has_no_problem(tmp_path: Path) -> None:
    the_plan = plan()
    prt.write_receipt(tmp_path, receipt(the_plan))
    assert prt.receipt_problems(the_plan, prt.load_receipts(tmp_path, "0001"), None) == []
    assert prt.receipt_holds(the_plan, prt.load_receipts(tmp_path, "0001"), "TASK-1")


def test_a_hand_edited_receipt_breaks_its_seal(tmp_path: Path) -> None:
    the_plan = plan()
    path = prt.write_receipt(tmp_path, receipt(the_plan))
    path.write_text(path.read_text(encoding="utf-8").replace("2026-11-10", "2026-11-12"), encoding="utf-8")
    loaded = prt.load_receipts(tmp_path, "0001")
    problems = prt.receipt_problems(the_plan, loaded, None)
    assert len(problems) == 1 and "TASK-1" in problems[0] and "seal" in problems[0]
    assert not prt.receipt_holds(the_plan, loaded, "TASK-1")


def test_a_receipt_copied_to_another_item_breaks_its_seal(tmp_path: Path) -> None:
    the_plan = plan()
    path = prt.write_receipt(tmp_path, receipt(the_plan))
    path.with_name("TASK-2.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    problems = prt.receipt_problems(the_plan, prt.load_receipts(tmp_path, "0001"), None)
    assert any("TASK-2" in p for p in problems)


def test_a_receipt_for_no_item_is_a_problem(tmp_path: Path) -> None:
    the_plan = plan()
    other = plan().model_copy(update={"items": [*plan().items[:1]]}, deep=True)
    stray = receipt(the_plan).model_copy(update={"item": "TASK-9"})
    prt.write_receipt(tmp_path, stray)
    problems = prt.receipt_problems(other, prt.load_receipts(tmp_path, "0001"), None)
    assert any("TASK-9" in p for p in problems)


def test_a_citation_needs_a_catalog_entry(tmp_path: Path) -> None:
    the_plan = plan()
    prt.write_receipt(tmp_path, receipt(the_plan, deviations=extra("EX9")))
    problems = prt.receipt_problems(the_plan, prt.load_receipts(tmp_path, "0001"), evolution(["TASK-1"]))
    assert any("EX9" in p and "TASK-1" in p for p in problems)


def test_a_citation_needs_an_entry_that_names_the_item(tmp_path: Path) -> None:
    the_plan = plan()
    prt.write_receipt(tmp_path, receipt(the_plan, deviations=extra()))
    problems = prt.receipt_problems(the_plan, prt.load_receipts(tmp_path, "0001"), evolution(["TASK-2"]))
    assert any("EX1" in p and "TASK-1" in p for p in problems)


def test_a_citation_without_a_catalog_is_a_problem() -> None:
    problems = prt.citation_problems(None, "TASK-1", extra())
    assert len(problems) == 1 and "EX1" in problems[0]


def test_a_matching_citation_passes() -> None:
    assert prt.citation_problems(evolution(["TASK-1"]), "TASK-1", extra()) == []


def test_a_status_set_in_the_plan_without_a_receipt_reads_pending(tmp_path: Path) -> None:
    raw = plan().model_dump(mode="json", exclude_none=True)
    raw["items"][1].update(status="COMPLETE", evidence="commit aaaaaaa")
    view = prt.status_view(ActionPlan.model_validate(raw), prt.load_receipts(tmp_path, "0001"))
    assert [i.status for i in view.items] == [ItemStatus.PENDING, ItemStatus.PENDING]


def test_a_cited_change_edited_after_the_receipt_is_a_problem(tmp_path: Path) -> None:
    the_plan = plan()
    prt.write_receipt(tmp_path, receipt(the_plan, deviations=extra()))
    edited = evolution(["TASK-1"])
    edited.changes[0].why_new_outcome.free_form = "reworded after the record"
    problems = prt.receipt_problems(the_plan, prt.load_receipts(tmp_path, "0001"), edited)
    assert len(problems) == 1 and "EX1" in problems[0] and "TASK-1" in problems[0] and "record" in problems[0]


def test_the_book_of_a_receipts_plan_reads_receipts(tmp_path: Path) -> None:
    the_plan = plan()
    prt.write_receipt(tmp_path, receipt(the_plan))
    ed.save_evolution(ed.catalog_path(tmp_path, "0001"), evolution(["TASK-1"]))
    book = prt.book_for(tmp_path, the_plan)
    assert book.status("TASK-1") == ItemStatus.COMPLETE and book.holds("TASK-1") and book.problems() == []
    assert book.nodes("TASK-1") == [NODE] and book.status("TASK-2") == ItemStatus.PENDING
    assert [i.status for i in book.view().items] == [ItemStatus.COMPLETE, ItemStatus.PENDING]


def test_the_book_of_a_sealed_plan_reads_the_plan_and_ignores_receipts(tmp_path: Path) -> None:
    sealed = plan(dict(FROZEN, records="sealed"))
    prt.write_receipt(tmp_path, receipt(sealed))
    book = prt.book_for(tmp_path, sealed)
    assert book.status("TASK-1") == ItemStatus.PENDING and not book.holds("TASK-1")
    assert book.problems() == [] and book.view() == sealed


@pytest.mark.parametrize("value, pair", [
    ("tests/a.py::t=tests/b.py::u", ("tests/a.py::t", "tests/b.py::u")),
    ("tests/a.py::t[x=1]=tests/b.py::u", ("tests/a.py::t[x=1]", "tests/b.py::u")),
    ("tests/a.py::t=tests/b.py::u[k=v]", ("tests/a.py::t", "tests/b.py::u[k=v]")),
    ("tests/a.py::t", None),
])
def test_a_substitution_splits_where_the_replacement_node_begins(value: str, pair: Optional[tuple]) -> None:
    assert prt.split_substitution(value) == pair
