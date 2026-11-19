"""``live.js``: the receipts and the DesignEvolution of a plan, as one script the HTML PIP reloads.

The file is ``window.PLAN_LIVE = <PlanLive JSON>;``. ``PlanLive`` is a closed model: the receipts sorted by
item id, the catalog or null, and the time it was built, so a page can say how old its data is. The file is
derived: the plan folder's ``.gitignore`` lists it, written by the driver, so no project has to.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_lib import evolution_doc as ed
from harness_lib import freeze_ledger as fl
from harness_lib import plan_doc as pd
from harness_lib import plan_live as pl
from harness_lib import plan_receipts as prt
from harness_lib.evolution_models import DesignEvolution
from harness_lib.plan_enums import RecordSource
from harness_lib.plan_models import ActionItem, Completed, PassedTests, Provenance
from harness_lib.receipt_models import Receipt

WALK_ROOTS = ()  # walks only tmp_path
NODE = "tests/test_calc_sub.py::test_sub"
HEAD = "window.PLAN_LIVE = "


def receipt(ident: str) -> Receipt:
    item = ActionItem.model_validate({"id": ident, "title": "Add sub", "action": "Add sub.",
                                      "status": "PENDING", "evidence": "not started",
                                      "files": ["src/calc.py"],
                                      "tests": [{"node": NODE, "red": "ImportError"}]})
    prov = Provenance(source=RecordSource.staged, tree="c" * 40)
    outcome = Completed.of(prov, PassedTests.of([NODE], ["python", "-m", "pytest", NODE]))
    return Receipt.sealed("0001", item, outcome=outcome, date="2026-11-10")


def evolution() -> DesignEvolution:
    return DesignEvolution.model_validate({
        "plan_id": "0001", "feature": "Add operators", "branch_lineage": "main-->feat-x",
        "primary_documents": {"plan": "docs/PLANS/0001_Add_operators_ActionPlan.json"}, "changes": []})


def parsed(path: Path) -> pl.PlanLive:
    text = path.read_text(encoding="utf-8").strip()
    assert text.startswith(HEAD) and text.endswith(";")
    return pl.PlanLive.model_validate(json.loads(text[len(HEAD):-1]))


def test_live_js_lands_in_the_plan_folder(tmp_path: Path) -> None:
    assert pl.live_path(tmp_path, "0001") == tmp_path / "0001" / "live.js"
    assert pl.write_live(tmp_path, "0001") == tmp_path / "0001" / "live.js"


def test_live_js_carries_the_receipts_by_item_id_and_the_evolution(tmp_path: Path) -> None:
    prt.write_receipt(tmp_path, receipt("TASK-2"))
    prt.write_receipt(tmp_path, receipt("TASK-1"))
    ed.save_evolution(ed.catalog_path(tmp_path, "0001"), evolution())
    live = parsed(pl.write_live(tmp_path, "0001"))
    assert [r.item for r in live.receipts] == ["TASK-1", "TASK-2"]
    assert live.evolution == evolution() and live.built


def test_live_js_without_receipts_or_catalog_is_empty(tmp_path: Path) -> None:
    live = parsed(pl.write_live(tmp_path, "0001"))
    assert live.receipts == [] and live.evolution is None


def test_the_live_payload_is_a_closed_model() -> None:
    assert pl.PlanLive.model_config.get("extra") == "forbid"


def test_the_plan_folder_ignores_live_js(tmp_path: Path) -> None:
    folder = tmp_path / "0001"
    folder.mkdir()
    (folder / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    pl.write_live(tmp_path, "0001")
    pl.write_live(tmp_path, "0001")
    assert (folder / ".gitignore").read_text(encoding="utf-8").splitlines() == ["scratch/", "live.js"]


# --- the plans a set of moved paths feeds, and the rebuild a-w runs for each -------------------------------

@pytest.mark.parametrize(("path", "plan_id"), [
    ("work/plans/0001/receipts/TASK-1.json", "0001"),
    ("work/plans/0002/DesignEvolution.json", "0002"),
    ("work/plans/0003_Add_operators_ActionPlan.json", "0003"),
    ("work/plans/freezes/plan/0004-add_operators/r1.1-freeze.json", "0004"),
])
def test_each_live_source_names_its_plan(path: str, plan_id: str) -> None:
    assert pl.sourced_plans([path], "work/plans") == [plan_id]


@pytest.mark.parametrize("path", [
    "work/plans/0001/tests/tests/test_calc.py", "work/plans/0001_Add_operators_PIP.html",
    "work/plans/0001/live.js", "work/plans/freezes/skill/retry/r1.1-freeze.json",
    "docs/plans/0001/receipts/TASK-1.json", "work/plans/0001/receipts/nested/TASK-1.json", "src/calc.py",
])
def test_other_paths_feed_no_plan(path: str) -> None:
    assert pl.sourced_plans([path], "work/plans") == []


def test_sourced_plans_are_unique_and_sorted() -> None:
    paths = ["work/plans/0002/receipts/TASK-1.json", "work/plans/0001/receipts/TASK-1.json",
             "work/plans/0002/receipts/TASK-2.json"]
    assert pl.sourced_plans(paths, "work/plans/") == ["0001", "0002"]


def _frozen_plan(plans: Path, records: str = "receipts", page: bool = True) -> None:
    """Plan 0001 with one ledger ``freeze`` entry on ``records``, and its HTML page unless ``page`` is off."""
    stem = fl.plan_stem("0001", "sample")
    raw = {"plan_id": "0001", "plan_created": "2026-11-10", "execution_model": "serial",
           "base_commit": "e" * 40, "ledger": stem,
           "items": [{"id": "TASK-1", "title": "Add sub", "action": "Add sub.", "status": "PENDING",
                      "evidence": "not started", "files": ["src/calc.py"],
                      "tests": [{"node": NODE, "red": "ImportError"}]}]}
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "0001_Sample_ActionPlan.json").write_text(json.dumps(raw), encoding="utf-8")
    entry = {"kind": "freeze", "round": 1, "seq": 1, "tree": "a" * 40, "at": "2026-11-11T09:30:00+00:00",
             "digest": "d" * 64, "records": records}
    fl.write_entry(fl.ledger_dir(plans, stem), fl.LedgerEntry.model_validate(entry))
    if page:
        (plans / "0001_Sample_PIP.html").write_text("<!DOCTYPE html>\n", encoding="utf-8")


def test_refresh_live_rebuilds_a_frozen_receipts_plan_with_a_page(tmp_path: Path) -> None:
    _frozen_plan(tmp_path)
    prt.write_receipt(tmp_path, receipt("TASK-1"))
    assert pl.refresh_live(tmp_path, "0001") == tmp_path / "0001" / "live.js"
    assert [r.item for r in parsed(tmp_path / "0001" / "live.js").receipts] == ["TASK-1"]


@pytest.mark.parametrize(("records", "page"), [("sealed", True), ("receipts", False)])
def test_refresh_live_skips_a_plan_the_page_does_not_reload(tmp_path: Path, records: str, page: bool) -> None:
    _frozen_plan(tmp_path, records=records, page=page)
    assert pl.refresh_live(tmp_path, "0001") is None
    assert not pl.live_path(tmp_path, "0001").exists()


def test_refresh_live_skips_a_plan_whose_file_is_gone(tmp_path: Path) -> None:
    prt.write_receipt(tmp_path, receipt("TASK-1"))
    assert pl.refresh_live(tmp_path, "0001") is None
    assert not pl.live_path(tmp_path, "0001").exists()


def test_refresh_live_raises_on_a_plan_that_does_not_load(tmp_path: Path) -> None:
    _frozen_plan(tmp_path)
    for entry in fl.ledger_dir(tmp_path, fl.plan_stem("0001", "sample")).iterdir():
        entry.unlink()
    with pytest.raises(pd.PlanError):
        pl.refresh_live(tmp_path, "0001")
