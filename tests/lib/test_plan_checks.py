"""Checks of ``plan_checks``: anchors against the tree, lint over commands, decisions and values, sweeps."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from harness_lib import plan_checks as pc
from harness_lib.plan_doc import validate_plan
from harness_lib.plan_models import ActionPlan

FILES = {
    "src/a.py": "def read(path):\n    return open(path).read()\n\n\ndef write(path, text):\n    pass\n",
    "src/old_name.py": "OLD_NAME = 1\n",
    "src/user.py": "from src.old_name import OLD_NAME\n",
    "tests/test_a.py": "def test_read():\n    pass\n",
}


def item(**extra: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {"id": "TASK-1", "title": "t", "action": "a", "status": "PENDING", "evidence": "e"}
    raw.update(extra)
    return raw


def plan(*items: Dict[str, Any], **top: Any) -> ActionPlan:
    raw = {"plan_id": "0001", "plan_created": "2026-10-29", "execution_model": "serial",
           "items": list(items) or [item()], **top}
    return validate_plan(raw)


def decision(chosen: Any = "split") -> Dict[str, Any]:
    return {"id": "D1", "question": "Split?", "chosen": chosen,
            "options": [{"id": "split", "summary": "two"}, {"id": "keep", "summary": "one"}]}


# --- anchors ----------------------------------------------------------------------------------------------

def anchor_plan(at: str, expect: str) -> ActionPlan:
    return plan(item(anchors=[{"at": at, "expect": expect}]))


def test_an_anchor_whose_text_sits_in_its_range_passes(make_project) -> None:
    root = make_project(files=FILES)
    assert pc.anchor_problems(anchor_plan("src/a.py:1-2", "return open(path).read()"), root) == []


def test_anchor_text_compares_runs_of_whitespace_as_one_space(make_project) -> None:
    root = make_project(files=FILES)
    assert pc.anchor_problems(anchor_plan("src/a.py:1-2", "def read(path):  return"), root) == []


def test_an_anchor_outside_its_range_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    problems = pc.anchor_problems(anchor_plan("src/a.py:1", "def write"), root)
    assert problems == ["anchor TASK-1 src/a.py:1: 'def write' not found; line 1 reads 'def read(path):'"]


def test_an_anchor_past_the_end_of_the_file_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    assert pc.anchor_problems(anchor_plan("src/a.py:40", "x"), root) == [
        "anchor TASK-1 src/a.py:40: the file has 6 lines"]


def test_an_anchor_on_a_missing_file_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    assert pc.anchor_problems(anchor_plan("src/gone.py:1", "x"), root) == [
        "anchor TASK-1 src/gone.py:1: no such file"]


def test_a_format_source_is_checked_as_an_anchor(make_project) -> None:
    root = make_project(files=FILES)
    fmt = {"name": "row", "example": "a b", "source": {"at": "src/a.py:5", "expect": "def read"}}
    problems = pc.anchor_problems(plan(formats=[fmt]), root)
    assert problems == ["anchor format row src/a.py:5: 'def read' not found; line 5 reads "
                        "'def write(path, text):'"]


# --- lint -------------------------------------------------------------------------------------------------

def lint(p: ActionPlan, root: Path) -> List[str]:
    return pc.lint_problems(p, root, root / "docs" / "PLANS")


def test_a_commit_sha_in_a_command_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    cmd = {"run": "git diff --binary 3c9049a13 HEAD", "expect": "a patch"}
    assert lint(plan(item(commands=[cmd])), root) == [
        "TASK-1 command names commit 3c9049a13; use {base} or git merge-base"]


def test_the_base_placeholder_and_plain_numbers_pass_the_sha_lint(make_project) -> None:
    root = make_project(files=FILES)
    cmd = {"run": "git diff {base} HEAD --stat 1234567", "expect": "a patch"}
    assert lint(plan(item(commands=[cmd])), root) == []


def test_a_pytest_run_of_a_directory_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    cmd = {"run": "python -m pytest tests -q", "expect": "passed"}
    assert lint(plan(item(commands=[cmd])), root) == [
        "TASK-1 command runs pytest on directory tests; name test files"]


def test_a_pytest_run_naming_no_file_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    cmd = {"run": "pytest -k read -q", "expect": "passed"}
    assert lint(plan(item(commands=[cmd])), root) == ["TASK-1 command runs pytest without naming a test file"]


def test_a_pytest_run_of_files_and_nodes_passes(make_project) -> None:
    root = make_project(files=FILES)
    cmd = {"run": "python -m pytest tests/test_a.py::test_read -k read -q", "expect": "1 passed"}
    assert lint(plan(item(commands=[cmd])), root) == []


def test_an_unknown_dependency_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    assert lint(plan(item(dependencies=["TASK-7"])), root) == ["TASK-1 depends on unknown item TASK-7"]


def test_a_dependency_cycle_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    first, second = item(dependencies=["TASK-2"]), item(id="TASK-2", dependencies=["TASK-1"])
    assert lint(plan(first, second), root) == ["dependency cycle among TASK-1, TASK-2"]


def test_a_duplicate_item_id_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    assert lint(plan(item(), item()), root) == ["item id TASK-1 is used 2 times"]


def test_a_chosen_option_outside_the_decision_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    expected = ["D1 chose merge, which is not one of its options"]
    assert lint(plan(decisions=[decision("merge")]), root) == expected


def test_a_value_assuming_a_rejected_option_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    value = {"name": "speedup", "value": "0.93", "source": "spec Section 4", "assumes": ["keep"]}
    assert lint(plan(decisions=[decision()], values=[value]), root) == [
        "value speedup assumes keep, which D1 rejected (chose split); recompute it or drop the assumption"]


def test_a_value_assuming_an_unknown_option_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    value = {"name": "speedup", "value": "0.93", "source": "spec", "assumes": ["fast"]}
    assert lint(plan(decisions=[decision()], values=[value]), root) == [
        "value speedup assumes unknown option fast"]


def test_a_test_file_neither_present_nor_planned_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    tests = [{"node": "tests/test_new.py::test_x", "red": "ImportError"},
             {"node": "tests/test_a.py::test_read", "red": "AssertionError"}]
    assert lint(plan(item(tests=tests)), root) == [
        "TASK-1 test tests/test_new.py::test_x: tests/test_new.py is neither in the tree nor planned at "
        "docs/PLANS/0001/tests/tests/test_new.py"]


def test_a_planned_test_file_satisfies_the_test_lint(make_project) -> None:
    root = make_project(files={**FILES, "docs/PLANS/0001/tests/tests/test_new.py": "def test_x(): pass\n"})
    tests = [{"node": "tests/test_new.py::test_x", "red": "ImportError"}]
    assert lint(plan(item(tests=tests)), root) == []


def test_open_decisions_are_listed_with_their_question() -> None:
    assert pc.open_decisions(plan(decisions=[decision(None)])) == ["D1: Split?"]
    assert pc.open_decisions(plan(decisions=[decision()])) == []


# --- sweeps -----------------------------------------------------------------------------------------------

def sweep_plan(hits: Dict[str, str]) -> ActionPlan:
    return plan(sweeps=[{"id": "S1", "pattern": "OLD_NAME|old_name", "hits": hits}])


def test_a_sweep_with_every_hit_classified_passes(make_project) -> None:
    root = make_project(files=FILES)
    hits = {"src/old_name.py": "rewrite", "src/user.py": "rewrite"}
    assert pc.sweep_problems(sweep_plan(hits), root, "docs/PLANS") == []


def test_an_unclassified_hit_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    assert pc.sweep_problems(sweep_plan({"src/old_name.py": "rewrite"}), root, "docs/PLANS") == [
        "sweep S1: src/user.py has hits but no classification"]


def test_a_classified_file_without_hits_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    hits = {"src/old_name.py": "rewrite", "src/user.py": "rewrite", "src/a.py": "keep"}
    assert pc.sweep_problems(sweep_plan(hits), root, "docs/PLANS") == [
        "sweep S1: src/a.py is classified but has no hit"]


def test_untracked_files_count_and_the_plans_folder_does_not(make_project) -> None:
    root = make_project(files={**FILES, "docs/PLANS/0001_x_ActionPlan.json": "OLD_NAME\n"})
    (root / "src" / "fresh.py").write_text("OLD_NAME\n", encoding="utf-8")
    hits = {"src/old_name.py": "rewrite", "src/user.py": "rewrite"}
    assert pc.sweep_problems(sweep_plan(hits), root, "docs/PLANS") == [
        "sweep S1: src/fresh.py has hits but no classification"]


def test_a_bad_pattern_is_a_problem(make_project) -> None:
    root = make_project(files=FILES)
    problems = pc.sweep_problems(plan(sweeps=[{"id": "S1", "pattern": "(", "hits": {}}]), root, "docs/PLANS")
    assert len(problems) == 1 and problems[0].startswith("sweep S1: git grep failed:")
