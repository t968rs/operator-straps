"""``plan.py record`` on the receipts scheme writes a receipt and ``live.js``, never the plan or its PIP.

A deviation from the item (``--also`` an extra file, ``--substitute`` a test node) needs a ``--cite`` of a
DesignChange in the plan's DesignEvolution that lists the item; a substituted node is the node run, by
``record`` and by ``verify``. Each ``--cite`` binds the deviations given before it, and the receipt keeps the
digest of each cited change, so editing that change later asks for a new record. The deviation flags need
``--sha`` or ``--staged`` and a receipts plan. Status reads (the dependency gate, ``lanes``, ``red``,
``verify``, the claims revision of ``check``) come from receipts; a refreeze keeps them, leaves the plan's
statuses PENDING and names each item whose seal it broke.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

from conftest import git

from harness_lib import evolution_api
from harness_lib.evolution_models import DesignChange
from harness_lib.plan_enums import ItemStatus
from harness_lib.receipt_models import Receipt

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_driver_helpers import (MUL_TEST, PLANS, SUB_TEST, Run, as_sealed, plan_file,  # noqa: E402
                                  read_plan, write_op, write_plan)

driver, project, run = helpers.driver, helpers.project, helpers.run  # the shared fixtures, by name
WALK_ROOTS = ()  # walks only a make_project repo and tmp_path/trees
SUB_NODE = "tests/test_calc_sub.py::test_sub"
MINUS_NODE = "tests/test_calc_minus.py::test_minus"
MINUS_TEST = "from src.calc import sub\n\n\ndef test_minus():\n    assert sub(5, 2) == 3\n"


def _item(item_id: str, name: str, deps: List[str]) -> Dict[str, Any]:
    return {"id": item_id, "title": f"Add {name}", "action": f"Add {name} beside add.", "status": "PENDING",
            "evidence": "not started", "files": ["src/calc.py", f"tests/test_calc_{name}.py"],
            "dependencies": deps or None,
            "anchors": [{"at": "src/calc.py:1", "expect": "def add(a, b):"}],
            "tests": [{"node": f"tests/test_calc_{name}.py::test_{name}", "red": "ImportError"}]}


def fill(run: Run, project: Path, *, two: bool = False, chained: bool = False) -> None:
    """``new``, the planned test files and TASK-1 (sub), plus TASK-2 (mul) when ``two``; then freeze."""
    code, _, err = run("new", "Add operators", "--spec", "docs/spec.md")
    assert code == 0, err
    planned = project / PLANS / "0001" / "tests" / "tests"
    planned.mkdir(parents=True, exist_ok=True)
    (planned / "test_calc_sub.py").write_text(SUB_TEST, encoding="utf-8")
    (planned / "test_calc_mul.py").write_text(MUL_TEST, encoding="utf-8")
    plan = read_plan(project)
    plan["items"] = [_item("TASK-1", "sub", [])]
    if two:
        plan["items"].append(_item("TASK-2", "mul", ["TASK-1"] if chained else []))
    write_plan(project, plan)
    code, _, err = run("freeze", "1")
    assert code == 0, err


def commit_op(root: Path, name: str) -> str:
    write_op(root, name)
    git(root, "add", "src/calc.py", f"tests/test_calc_{name}.py")
    git(root, "commit", "-q", "-m", f"add {name}")
    return git(root, "rev-parse", "HEAD")


def receipt_file(project: Path, item: str) -> Path:
    return project / PLANS / "0001" / "receipts" / f"{item}.json"


def receipt(project: Path, item: str = "TASK-1") -> Receipt:
    return Receipt.model_validate_json(receipt_file(project, item).read_text(encoding="utf-8"))


def cite(project: Path, ident: str = "EX1", items: Sequence[str] = ("TASK-1",)) -> None:
    """Add a post-exec-start DesignChange naming ``items`` to the plan's DesignEvolution."""
    evolution_api.add("1", DesignChange.model_validate({
        "id": ident, "discovered_by": "implementer", "phase": "post-exec-start", "items": list(items),
        "original": {"doc": "plan", "location": "TASK-1", "indicated": "the planned files and nodes"},
        "issue": {"category": "spec-coverage", "why_categorical": "x", "why_free_form": "y"},
        "new_outcome": {"doc": "plan", "indicated": "a helper module and another test"},
        "why_new_outcome": {"category": "execution-blocker", "free_form": "z"}}), repo=project)


def commit_helper(project: Path) -> str:
    """Commit sub through a helper module the plan does not name, and its planned test."""
    (project / "src" / "helper.py").write_text("def minus(a, b):\n    return a - b\n", encoding="utf-8")
    calc = project / "src" / "calc.py"
    calc.write_text(calc.read_text(encoding="utf-8") + "\n\ndef sub(a, b):\n    from src.helper import minus\n"
                    "    return minus(a, b)\n", encoding="utf-8")
    (project / "tests" / "test_calc_sub.py").write_text(SUB_TEST, encoding="utf-8")
    git(project, "add", "src", "tests")
    git(project, "commit", "-q", "-m", "add sub through a helper")
    return git(project, "rev-parse", "HEAD")


def commit_minus(project: Path) -> str:
    """Commit sub with a test of another name than the planned one."""
    calc = project / "src" / "calc.py"
    calc.write_text(calc.read_text(encoding="utf-8") + "\n\ndef sub(a, b):\n    return a - b\n", encoding="utf-8")
    (project / "tests" / "test_calc_minus.py").write_text(MINUS_TEST, encoding="utf-8")
    git(project, "add", "src", "tests")
    git(project, "commit", "-q", "-m", "add sub with test_minus")
    return git(project, "rev-parse", "HEAD")


def commit_both(project: Path) -> str:
    """Commit sub through the helper module, then the test of another name; return HEAD."""
    commit_helper(project)
    (project / "tests" / "test_calc_minus.py").write_text(MINUS_TEST, encoding="utf-8")
    git(project, "add", "tests")
    git(project, "commit", "-q", "-m", "add test_minus")
    return git(project, "rev-parse", "HEAD")


def test_record_writes_the_receipt_and_live_js_and_nothing_of_the_plan(run: Run, project: Path) -> None:
    fill(run, project)
    pip = project / PLANS / "0001_Add_operators_PIP.html"
    before = (plan_file(project).read_bytes(), pip.read_bytes())
    sha = commit_op(project, "sub")
    code, out, err = run("record", "1", "TASK-1", "--sha", sha)
    assert code == 0, err
    assert (plan_file(project).read_bytes(), pip.read_bytes()) == before
    found = receipt(project)
    assert found.status == ItemStatus.COMPLETE and found.outcome.provenance.commit == sha
    assert found.outcome.tests.nodes == [SUB_NODE]
    assert '"TASK-1"' in (project / PLANS / "0001" / "live.js").read_text(encoding="utf-8")
    assert out.startswith("record [done] | TASK-1 COMPLETE") and run("check", "1")[0] == 0


def test_check_reads_the_claims_at_the_base_once_a_receipt_completes_an_item(run: Run, project: Path) -> None:
    fill(run, project)
    assert run("record", "1", "TASK-1", "--sha", commit_op(project, "sub"))[0] == 0
    assert receipt_file(project, "TASK-1").is_file()
    code, out, err = run("check", "1")
    assert code == 0, err
    assert "anchors and sweeps at base" in out


def test_check_flags_a_hand_edited_receipt(run: Run, project: Path) -> None:
    fill(run, project)
    assert run("record", "1", "TASK-1", "--sha", commit_op(project, "sub"))[0] == 0
    path = receipt_file(project, "TASK-1")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["evidence"] = "commit 1234567: 9 test node(s) passed"
    path.write_text(json.dumps(data), encoding="utf-8")
    code, _, err = run("check", "1")
    assert code == 1 and "TASK-1" in err and "seal" in err


def test_record_start_and_closed_write_receipts(run: Run, project: Path) -> None:
    fill(run, project)
    assert run("record", "1", "TASK-1", "--start")[0] == 0
    assert receipt(project).status == ItemStatus.IN_PROGRESS
    assert run("record", "1", "TASK-1", "--closed", "superseded by the operator module")[0] == 0
    assert receipt(project).status == ItemStatus.CLOSED_NO_ACTION
    assert read_plan(project)["items"][0]["status"] == "PENDING" and "completed" not in read_plan(project)


def test_record_also_with_a_valid_citation_passes(run: Run, project: Path) -> None:
    fill(run, project)
    cite(project)
    sha = commit_helper(project)
    code, _, err = run("record", "1", "TASK-1", "--sha", sha, "--also", "src/helper.py", "--cite", "EX1")
    assert code == 0, err
    found = receipt(project).deviations
    assert [(e.path, e.change) for e in found.extra_files] == [("src/helper.py", "EX1")]
    assert found.change_digests == {"EX1": evolution_api.load("1", repo=project).find("EX1").digest()}
    assert run("check", "1")[0] == 0


def test_each_cite_binds_the_deviations_before_it(run: Run, project: Path) -> None:
    fill(run, project)
    cite(project, "EX1")
    cite(project, "EX2")
    sha = commit_both(project)
    code, _, err = run("record", "1", "TASK-1", "--sha", sha, "--also", "src/helper.py", "--cite", "EX1",
                       "--substitute", f"{SUB_NODE}={MINUS_NODE}", "--cite", "EX2")
    assert code == 0, err
    found = receipt(project).deviations
    assert [(e.path, e.change) for e in found.extra_files] == [("src/helper.py", "EX1")]
    assert [(s.planned, s.change) for s in found.substitutions] == [(SUB_NODE, "EX2")]
    assert sorted(found.change_digests) == ["EX1", "EX2"]


def test_editing_a_cited_change_asks_for_a_new_record(run: Run, project: Path) -> None:
    fill(run, project)
    cite(project)
    sha = commit_helper(project)
    assert run("record", "1", "TASK-1", "--sha", sha, "--also", "src/helper.py", "--cite", "EX1")[0] == 0
    evo = evolution_api.load("1", repo=project)
    evo.changes[0].why_new_outcome.free_form = "reworded after the record"
    evolution_api.write(evo, repo=project)
    code, _, err = run("check", "1")
    assert code == 1 and "EX1" in err and "TASK-1" in err


def test_the_deviation_flags_are_refused_on_a_sealed_plan(run: Run, project: Path) -> None:
    fill(run, project)
    as_sealed(project)
    sha = commit_helper(project)
    code, _, err = run("record", "1", "TASK-1", "--sha", sha, "--also", "src/helper.py", "--cite", "EX1")
    assert code == 1 and "--also" in err and not receipt_file(project, "TASK-1").exists()


def test_the_deviation_flags_need_sha_or_staged(run: Run, project: Path) -> None:
    fill(run, project)
    cite(project)
    code, _, err = run("record", "1", "TASK-1", "--start", "--also", "src/helper.py", "--cite", "EX1")
    assert code == 1 and "--also" in err and not receipt_file(project, "TASK-1").exists()


def test_an_extra_file_joins_the_clean_path_rule(run: Run, project: Path) -> None:
    fill(run, project)
    cite(project)
    sha = commit_helper(project)
    (project / "src" / "helper.py").write_text("def minus(a, b):\n    return b - a\n", encoding="utf-8")
    code, _, err = run("record", "1", "TASK-1", "--sha", sha, "--also", "src/helper.py", "--cite", "EX1")
    assert code == 1 and "src/helper.py" in err


def test_a_deviation_without_a_cite_is_refused(run: Run, project: Path) -> None:
    fill(run, project)
    sha = commit_helper(project)
    code, _, err = run("record", "1", "TASK-1", "--sha", sha, "--also", "src/helper.py")
    assert code == 1 and "src/helper.py" in err and "--cite" in err and "evolution_api.add" in err
    assert not receipt_file(project, "TASK-1").exists()


def test_a_citation_missing_from_the_catalog_is_refused(run: Run, project: Path) -> None:
    fill(run, project)
    cite(project)
    sha = commit_helper(project)
    code, _, err = run("record", "1", "TASK-1", "--sha", sha, "--also", "src/helper.py", "--cite", "EX9")
    assert code == 1 and "EX9" in err and "TASK-1" in err


def test_a_citation_that_does_not_list_the_item_is_refused(run: Run, project: Path) -> None:
    fill(run, project, two=True)
    cite(project, items=["TASK-2"])
    sha = commit_helper(project)
    code, _, err = run("record", "1", "TASK-1", "--sha", sha, "--also", "src/helper.py", "--cite", "EX1")
    assert code == 1 and "EX1" in err and "TASK-1" in err


def test_a_substituted_node_is_the_node_run_and_verified(run: Run, project: Path) -> None:
    fill(run, project)
    cite(project)
    sha = commit_minus(project)
    code, _, err = run("record", "1", "TASK-1", "--sha", sha,
                       "--substitute", f"{SUB_NODE}={MINUS_NODE}", "--cite", "EX1")
    assert code == 0, err
    found = receipt(project)
    assert found.outcome.tests.nodes == [MINUS_NODE]
    assert [(s.planned, s.node, s.change) for s in found.deviations.substitutions] == [
        (SUB_NODE, MINUS_NODE, "EX1")]
    code, out, err = run("verify", "1")
    assert code == 0, err
    assert "TASK-1 pass" in out


def test_a_dirty_substituted_test_file_refuses_the_record(run: Run, project: Path) -> None:
    fill(run, project)
    cite(project)
    sha = commit_minus(project)
    (project / "tests" / "test_calc_minus.py").write_text(MINUS_TEST + "# edited", encoding="utf-8")
    code, _, err = run("record", "1", "TASK-1", "--sha", sha,
                       "--substitute", f"{SUB_NODE}={MINUS_NODE}", "--cite", "EX1")
    assert code == 1 and "tests/test_calc_minus.py" in err


def test_a_substitute_must_replace_a_planned_node(run: Run, project: Path) -> None:
    fill(run, project)
    cite(project)
    sha = commit_minus(project)
    code, _, err = run("record", "1", "TASK-1", "--sha", sha,
                       "--substitute", f"tests/test_calc_x.py::test_x={MINUS_NODE}", "--cite", "EX1")
    assert code == 1 and "tests/test_calc_x.py::test_x" in err


def test_record_sha_accepts_a_tag_and_keeps_it(run: Run, project: Path) -> None:
    fill(run, project)
    sha = commit_op(project, "sub")
    git(project, "tag", "v-sub")
    assert run("record", "1", "TASK-1", "--sha", "v-sub")[0] == 0
    found = receipt(project)
    assert found.ref == "v-sub" and found.outcome.provenance.commit == sha


def test_the_dependency_gate_reads_receipts(run: Run, project: Path) -> None:
    fill(run, project, two=True, chained=True)
    sha = commit_op(project, "sub")
    assert run("record", "1", "TASK-1", "--sha", sha)[0] == 0
    receipt_file(project, "TASK-1").unlink()
    code, _, err = run("record", "1", "TASK-2", "--sha", commit_op(project, "mul"))
    assert code == 1 and "TASK-2 depends on TASK-1, which is PENDING" in err
    head = git(project, "rev-parse", "HEAD")
    assert head != sha and run("record", "1", "TASK-1", "--sha", head)[0] == 0
    assert run("record", "1", "TASK-2", "--sha", head)[0] == 0


def test_lanes_lists_only_items_without_a_done_receipt(run: Run, project: Path) -> None:
    fill(run, project, two=True)
    assert run("record", "1", "TASK-1", "--sha", commit_op(project, "sub"))[0] == 0
    assert receipt_file(project, "TASK-1").is_file()
    code, out, err = run("lanes", "1", "--target", "feat-x")
    assert code == 0, err
    assert [lane["id"] for lane in json.loads(out)["lanes"]] == ["task-2"]


def test_red_runs_only_the_items_without_a_done_receipt(run: Run, project: Path) -> None:
    fill(run, project, two=True)
    assert run("record", "1", "TASK-1", "--sha", commit_op(project, "sub"))[0] == 0
    code, out, err = run("red", "1")
    assert code == 0, err
    assert "TASK-2" in out and "TASK-1" not in out


def test_verify_names_a_receipt_whose_seal_is_broken(run: Run, project: Path) -> None:
    fill(run, project)
    assert run("record", "1", "TASK-1", "--sha", commit_op(project, "sub"))[0] == 0
    path = receipt_file(project, "TASK-1")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["evidence"] = "commit 1234567: 9 test node(s) passed"
    path.write_text(json.dumps(data), encoding="utf-8")
    code, _, err = run("verify", "1")
    assert code == 1 and "TASK-1" in err and "record" in err


def test_a_refreeze_keeps_receipts_and_names_each_broken_seal(run: Run, project: Path) -> None:
    fill(run, project, two=True)
    assert run("record", "1", "TASK-1", "--sha", commit_op(project, "sub"))[0] == 0
    plan = read_plan(project)
    plan["items"][0]["files"].append("src/__init__.py")
    write_plan(project, plan)
    code, out, err = run("freeze", "1", "--refreeze")
    assert code == 0, err
    assert "re-record after refreeze: TASK-1" in out and receipt_file(project, "TASK-1").is_file()
    saved = read_plan(project)
    assert all(i["status"] == "PENDING" for i in saved["items"]) and "completed" not in saved
    code, _, err = run("check", "1")
    assert code == 1 and "TASK-1" in err
