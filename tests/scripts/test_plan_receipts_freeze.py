"""``plan.py`` on the receipts scheme: the HTML PIP, the first freeze, and ``check`` of a frozen plan.

A plan frozen for the first time stores ``records: receipts``. From then on no field of its JSON may change
(the freeze digest covers every field but ``frozen``), its PIP is the HTML page rendered at freeze, and
``check`` also validates the receipts and the plan's DesignEvolution. ``render`` rebuilds ``live.js`` and
writes a frozen page only when it is missing. A first freeze moves a plan written before receipts (its
``documentation`` naming the markdown PIP) to the HTML page. Plans frozen as sealed keep markdown.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from harness_lib import plan_api
from harness_lib import plan_doc as pd
from harness_lib import plan_receipts as prt

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_driver_helpers import (  # noqa: E402
    PLANS, SUB_TEST, Run, as_sealed, plan_file, read_plan, write_plan,
)

driver, project, run = helpers.driver, helpers.project, helpers.run  # the shared fixtures, by name
WALK_ROOTS = ()  # walks only a make_project repo and tmp_path/trees
HTML = f"{PLANS}/0001_Add_operators_PIP.html"
MD = f"{PLANS}/0001_Add_operators_PIP.md"


def _item() -> Dict[str, Any]:
    return {"id": "TASK-1", "title": "Add sub", "action": "Add sub beside add.", "status": "PENDING",
            "evidence": "not started", "files": ["src/calc.py", "tests/test_calc_sub.py"],
            "anchors": [{"at": "src/calc.py:1", "expect": "def add(a, b):"}],
            "tests": [{"node": "tests/test_calc_sub.py::test_sub", "red": "ImportError"}]}


def fill(run: Run, project: Path, freeze: bool = True) -> None:
    """``new``, the planned test file and TASK-1; then freeze unless told not to."""
    code, _, err = run("new", "Add operators", "--spec", "docs/spec.md")
    assert code == 0, err
    planned = project / PLANS / "0001" / "tests" / "tests"
    planned.mkdir(parents=True, exist_ok=True)
    (planned / "test_calc_sub.py").write_text(SUB_TEST, encoding="utf-8")
    plan = read_plan(project)
    plan["items"] = [_item()]
    write_plan(project, plan)
    if freeze:
        code, _, err = run("freeze", "1")
        assert code == 0, err


def test_new_writes_an_html_pip_and_names_it_as_documentation(run: Run, project: Path) -> None:
    fill(run, project, freeze=False)
    assert (project / HTML).is_file() and not (project / MD).exists()
    assert read_plan(project)["documentation"] == HTML


def test_a_first_freeze_stores_the_receipts_scheme_and_writes_live_js(run: Run, project: Path) -> None:
    fill(run, project)
    assert read_plan(project)["frozen"]["records"] == "receipts"
    assert prt.uses_receipts(pd.load_plan(plan_file(project)))
    live = project / PLANS / "0001" / "live.js"
    assert live.read_text(encoding="utf-8").startswith("window.PLAN_LIVE = ")
    assert "0001/live.js" in (project / HTML).read_text(encoding="utf-8")


def test_check_passes_a_frozen_receipts_plan(run: Run, project: Path) -> None:
    fill(run, project)
    assert read_plan(project)["frozen"]["records"] == "receipts"
    assert (project / PLANS / "0001" / "live.js").is_file()
    code, out, err = run("check", "1")
    assert code == 0, err
    assert out.startswith("check [ok] | plan 0001")


def test_check_flags_a_formerly_mutable_field_edited_after_freeze(run: Run, project: Path) -> None:
    fill(run, project)
    plan = read_plan(project)
    plan["completed"] = "2026-11-10"
    write_plan(project, plan)
    code, _, err = run("check", "1")
    assert code == 1 and "problem: plan changed after freeze" in err


def test_check_flags_a_hand_set_status_as_a_plan_change(run: Run, project: Path) -> None:
    fill(run, project)
    plan = read_plan(project)
    plan["items"][0].update(status="COMPLETE", evidence="commit aaaaaaa")
    write_plan(project, plan)
    code, _, err = run("check", "1")
    assert code == 1 and "problem: plan changed after freeze" in err


def test_check_reports_a_receipt_that_does_not_parse(run: Run, project: Path) -> None:
    fill(run, project)
    folder = project / PLANS / "0001" / "receipts"
    folder.mkdir(parents=True)
    (folder / "TASK-9.json").write_text("{}", encoding="utf-8")
    code, _, err = run("check", "1")
    assert code == 1 and "TASK-9" in err


def test_check_reports_a_design_evolution_that_does_not_validate(run: Run, project: Path) -> None:
    fill(run, project)
    path = project / PLANS / "0001" / "DesignEvolution.json"
    path.write_text(json.dumps({"plan_id": "0001"}), encoding="utf-8")
    code, _, err = run("check", "1")
    assert code == 1 and "problem: schema: " in err


def test_render_writes_the_html_pip_of_a_receipts_plan(run: Run, project: Path) -> None:
    fill(run, project)
    (project / HTML).unlink()
    code, out, err = run("render", "1")
    assert code == 0, err
    assert out == f"render [done] | {HTML}\n" and (project / HTML).is_file()


def test_render_leaves_a_frozen_page_alone_and_rebuilds_live_js(run: Run, project: Path) -> None:
    fill(run, project)
    page = project / HTML
    page.write_bytes(page.read_bytes() + b"<!-- edited -->")
    before = page.read_bytes()
    live = project / PLANS / "0001" / "live.js"
    live.unlink()
    code, _, err = run("render", "1")
    assert code == 0, err
    assert page.read_bytes() == before and live.is_file()


def test_a_sealed_plan_still_renders_markdown(run: Run, project: Path) -> None:
    fill(run, project)
    as_sealed(project)
    code, out, err = run("render", "1")
    assert code == 0, err
    assert out == f"render [done] | {MD}\n"
    assert (project / MD).read_text(encoding="utf-8").startswith("# Plan 0001")


def test_plan_api_write_renders_the_html_pip_of_an_unfrozen_plan(run: Run, project: Path) -> None:
    fill(run, project, freeze=False)
    (project / HTML).unlink()
    loaded = plan_api.load("1", repo=project)
    plan_api.write(loaded.model_copy(update={"execution_model": "parallel"}, deep=True), repo=project)
    assert (project / HTML).is_file() and not (project / MD).exists()
    assert not (project / PLANS / "0001" / "live.js").exists()


def test_a_first_freeze_moves_a_markdown_pip_to_html(run: Run, project: Path) -> None:
    fill(run, project, freeze=False)
    (project / HTML).unlink()
    (project / MD).write_text("# Plan 0001", encoding="utf-8")
    plan = read_plan(project)
    plan["documentation"] = MD
    write_plan(project, plan)
    code, _, err = run("freeze", "1")
    assert code == 0, err
    assert read_plan(project)["documentation"] == HTML and (project / HTML).is_file()
    assert not (project / MD).exists() and run("check", "1")[0] == 0


def test_a_refreeze_of_a_receipts_plan_keeps_the_scheme(run: Run, project: Path) -> None:
    fill(run, project)
    plan = read_plan(project)
    plan["items"][0]["title"] = "Add subtraction"
    write_plan(project, plan)
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 0, err
    assert read_plan(project)["frozen"]["records"] == "receipts" and run("check", "1")[0] == 0


def test_a_refreeze_keeps_receipts_when_the_scheme_is_deleted_by_hand(run: Run, project: Path) -> None:
    fill(run, project)
    plan = read_plan(project)
    del plan["frozen"]["records"]
    write_plan(project, plan)
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 0, err
    assert read_plan(project)["frozen"]["records"] == "receipts"
