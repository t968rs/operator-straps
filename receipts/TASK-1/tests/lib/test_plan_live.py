"""``live.js``: the receipts and the DesignEvolution of a plan, as one script the HTML PIP reloads.

The file is ``window.PLAN_LIVE = <PlanLive JSON>;``. ``PlanLive`` is a closed model: the receipts sorted by
item id, the catalog or null, and the time it was built, so a page can say how old its data is. The file is
derived: the plan folder's ``.gitignore`` lists it, written by the driver, so no project has to.
"""
from __future__ import annotations

import json
from pathlib import Path

from harness_lib import evolution_doc as ed
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
    item = ActionItem.model_validate({"id": ident, "title": "Add sub", "action": "Add sub.", "status": "PENDING",
                                      "evidence": "not started", "files": ["src/calc.py"],
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
