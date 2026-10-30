"""Behavioral tests of the plugin's ``scripts/plan.py`` against throwaway git repositories.

Each test gets a project on branch ``feat-x`` cut from ``main``. The driver runs in-process through ``main``
with ``--repo``; the plan JSON and PIP are read back from disk.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Optional, Tuple

import pytest
from conftest import git

Result = Tuple[int, str, str]
Run = Callable[..., Result]
Fill = Callable[..., Dict[str, Any]]
BASE_FILES = {
    "src/calc.py": "def add(a, b):\n    return a + b\n",
    "tests/test_calc.py": "from src.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    "docs/spec.md": "# Spec\n\nAdd subtraction.\n",
}
PLANS = "docs/PLANS"


@pytest.fixture(scope="module")
def driver(plugin_root: Path) -> ModuleType:
    """Import plan.py by absolute path."""
    path = plugin_root / "scripts" / "plan.py"
    spec = importlib.util.spec_from_file_location("plan_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def project(make_project, tmp_path: Path) -> Path:
    """A project on ``feat-x``; red-run worktrees land in ``tmp_path/trees``."""
    config = {"base_branch": "main", "worktree_root": (tmp_path / "trees").as_posix()}
    root = make_project(config, files={**BASE_FILES, "src/__init__.py": ""})
    git(root, "checkout", "-q", "-b", "feat-x")
    return root


@pytest.fixture()
def run(driver: ModuleType, project: Path, capsys: pytest.CaptureFixture) -> Callable[..., Result]:
    """``run(*args)`` -> (exit code, stdout, stderr) of ``plan.py --repo <project> *args``."""
    def _run(*args: str) -> Result:
        code = driver.main(["--repo", str(project), *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err
    return _run


def plan_file(project: Path) -> Path:
    return next((project / PLANS).glob("*_ActionPlan.json"))


def read_plan(project: Path) -> Dict[str, Any]:
    return json.loads(plan_file(project).read_text(encoding="utf-8"))


def write_plan(project: Path, plan: Dict[str, Any]) -> None:
    plan_file(project).write_text(json.dumps(plan, indent=2), encoding="utf-8")


def sub_item(**extra: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "id": "TASK-1", "title": "Add subtraction", "action": "Add sub beside add.", "status": "PENDING",
        "evidence": "not started", "files": ["src/calc.py", "tests/test_calc_sub.py"],
        "anchors": [{"at": "src/calc.py:1", "expect": "def add(a, b):"}],
        "tests": [{"node": "tests/test_calc_sub.py::test_sub", "red": "ImportError"}],
    }
    raw.update(extra)
    return raw


@pytest.fixture()
def filled(run: Run, project: Path) -> Callable[..., Dict[str, Any]]:
    """``filled(item=None, **top)``: run ``new``, then write one item and the ``top`` fields.

    ``item`` defaults to ``sub_item()``.
    """
    def _fill(item: Optional[Dict[str, Any]] = None, **top: Any) -> Dict[str, Any]:
        code, _, err = run("new", "Add subtraction", "--spec", "docs/spec.md")
        assert code == 0, err
        planned = project / PLANS / "0001" / "tests" / "tests" / "test_calc_sub.py"
        planned.parent.mkdir(parents=True, exist_ok=True)
        planned.write_text("from src.calc import sub\n\n\ndef test_sub():\n    assert sub(3, 1) == 2\n",
                           encoding="utf-8")
        plan = read_plan(project)
        plan["items"] = [item or sub_item()]
        plan.update(top)
        write_plan(project, plan)
        return plan
    return _fill


def implement(project: Path) -> str:
    """Commit the planned test and the implementation; return the commit SHA."""
    source = project / PLANS / "0001" / "tests" / "tests" / "test_calc_sub.py"
    (project / "tests" / "test_calc_sub.py").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    calc = project / "src" / "calc.py"
    body = calc.read_text(encoding="utf-8") + "\n\ndef sub(a, b):\n    return a - b\n"
    calc.write_text(body, encoding="utf-8")
    git(project, "add", "src/calc.py", "tests/test_calc_sub.py")
    git(project, "commit", "-q", "-m", "add sub")
    return git(project, "rev-parse", "HEAD")


# --- new --------------------------------------------------------------------------------------------------

def test_new_writes_the_plan_and_its_pip_with_the_merge_base(run: Run, project: Path) -> None:
    main_sha = git(project, "rev-parse", "main")
    code, out, err = run("new", "Add subtraction", "--spec", "docs/spec.md")
    assert code == 0, err
    plan = read_plan(project)
    assert plan_file(project).name == "0001_Add_subtraction_ActionPlan.json"
    assert plan["base_commit"] == main_sha and plan["base_branch"] == "main" and plan["branch"] == "feat-x"
    assert plan["source_document"] == "docs/spec.md" and plan["items"] == [] and plan["frozen"] is None
    assert (project / PLANS / "0001_Add_subtraction_PIP.md").is_file()
    assert out.startswith(f"new [done] | plan 0001 | base main @ {main_sha[:7]}")


def test_new_prints_the_authoring_command_line(run: Run, plugin_root: Path) -> None:
    code, out, err = run("new", "Add subtraction", "--spec", "docs/spec.md")
    assert code == 0, err
    author = next(line for line in out.splitlines() if line.startswith("author: "))
    assert f'PYTHONPATH="{plugin_root.as_posix()}/lib"' in author and "- <<'EOF'" in author
    assert 'plan_api.load("0001")' in author


@pytest.mark.parametrize("command", [("render", "1"), ("red", "1"), ("lanes", "1"),
                                     ("record", "1", "TASK-1", "--start"), ("freeze", "1")])
def test_every_command_refuses_a_plan_that_does_not_validate(run: Run, filled: Fill,
                                                             command: Tuple[str, ...]) -> None:
    filled(sub_item(tests=[{"node": "tests/test_calc_sub.py::test_sub", "red": "Oops"}]))
    code, _, err = run(*command)
    assert code == 1 and "problem: schema: items/0/tests/0/red:" in err


def test_new_refuses_a_missing_spec(run: Run) -> None:
    code, _, err = run("new", "Add subtraction", "--spec", "docs/nope.md")
    assert code == 1 and "problem: spec docs/nope.md does not exist" in err


def test_a_second_plan_takes_the_next_id(run: Run, project: Path) -> None:
    run("new", "First")
    code, out, _ = run("new", "Second")
    assert code == 0 and "plan 0002" in out


# --- check ------------------------------------------------------------------------------------------------

def test_check_passes_a_sound_plan(run: Run, filled: Fill) -> None:
    filled()
    code, out, err = run("check", "1")
    assert code == 0, err
    assert out.startswith("check [ok] | plan 0001 | 1 items, 1 anchors, 0 sweeps")


def test_check_reports_a_stale_anchor(run: Run, filled: Fill) -> None:
    filled(sub_item(anchors=[{"at": "src/calc.py:1", "expect": "def plus(a, b):"}]))
    code, _, err = run("check", "1")
    assert code == 1 and "problem: anchor TASK-1 src/calc.py:1: 'def plus(a, b):' not found" in err


def test_check_stops_at_schema_problems(run: Run, filled: Fill) -> None:
    stale = [{"at": "src/calc.py:1", "expect": "def plus(a, b):"}]
    filled(sub_item(tests=[{"node": "tests/test_calc_sub.py::test_sub", "red": "Oops"}], anchors=stale))
    code, _, err = run("check", "1")
    assert code == 1 and "problem: schema: items/0/tests/0/red:" in err and "anchor" not in err


def test_check_lists_open_decisions_without_failing(run: Run,
                                                    filled: Fill) -> None:
    decision = {"id": "D1", "question": "Name it sub?", "chosen": None,
                "options": [{"id": "sub", "summary": "sub"}, {"id": "minus", "summary": "minus"}]}
    filled(decisions=[decision])
    code, out, _ = run("check", "1")
    assert code == 0 and "open: D1: Name it sub?" in out


def test_render_writes_the_pip_from_the_plan(run: Run, filled: Fill, project: Path) -> None:
    filled()
    pip = project / PLANS / "0001_Add_subtraction_PIP.md"
    pip.unlink()
    code, out, err = run("render", "1")
    assert code == 0, err
    assert out == f"render [done] | {PLANS}/0001_Add_subtraction_PIP.md\n"
    assert "TASK-1" in pip.read_text(encoding="utf-8")


# --- freeze -----------------------------------------------------------------------------------------------

def test_freeze_refuses_an_open_decision(run: Run, filled: Fill, project: Path) -> None:
    decision = {"id": "D1", "question": "Name it sub?", "chosen": None,
                "options": [{"id": "sub", "summary": "sub"}, {"id": "minus", "summary": "minus"}]}
    filled(decisions=[decision])
    before = read_plan(project)
    code, _, err = run("freeze", "1")
    assert code == 1 and "problem: decision D1 is open: Name it sub?" in err
    assert read_plan(project) == before


def test_freeze_refuses_an_item_nothing_proves(run: Run,
                                              filled: Fill, project: Path) -> None:
    filled(sub_item(tests=[]))
    before = read_plan(project)
    code, _, err = run("freeze", "1")
    assert code == 1 and "problem: TASK-1 has no test and no command" in err
    assert read_plan(project) == before


@pytest.mark.cross_os
def test_freeze_records_head_and_renders(run: Run, filled: Fill,
                                         project: Path) -> None:
    filled()
    code, out, err = run("freeze", "1")
    assert code == 0, err
    frozen = read_plan(project)["frozen"]
    assert frozen["commit"] == git(project, "rev-parse", "HEAD")
    assert frozen["tree"] == git(project, "rev-parse", "HEAD^{tree}")
    assert out.startswith("freeze [done] | plan 0001")
    pip = (project / PLANS / "0001_Add_subtraction_PIP.md").read_text(encoding="utf-8")
    assert "**Frozen:** " + frozen["date"] in pip


def test_a_second_freeze_needs_refreeze(run: Run, filled: Fill, project: Path) -> None:
    filled()
    run("freeze", "1")
    before = read_plan(project)
    code, _, err = run("freeze", "1")
    assert code == 1 and "already frozen" in err
    assert read_plan(project) == before
    assert run("freeze", "1", "--refreeze")[0] == 0


def test_check_flags_an_edit_after_freeze(run: Run, filled: Fill,
                                          project: Path) -> None:
    filled()
    run("freeze", "1")
    plan = read_plan(project)
    plan["items"][0]["action"] = "Add sub and mul."
    write_plan(project, plan)
    code, _, err = run("check", "1")
    assert code == 1 and "problem: plan changed after freeze" in err


def test_check_flags_a_hand_set_complete_item(run: Run, filled: Fill, project: Path) -> None:
    filled()
    run("freeze", "1")
    plan = read_plan(project)
    plan["items"][0]["status"] = "COMPLETE"
    write_plan(project, plan)
    code, _, err = run("check", "1")
    assert code == 1 and "problem: TASK-1 is COMPLETE without the record of record --sha" in err


def test_freeze_refuses_an_item_that_is_not_pending(run: Run, filled: Fill, project: Path) -> None:
    filled(sub_item(status="IN_PROGRESS"))
    before = read_plan(project)
    code, _, err = run("freeze", "1")
    assert code == 1 and "problem: TASK-1 is IN_PROGRESS: a first freeze needs every item PENDING" in err
    assert read_plan(project) == before


# --- record -----------------------------------------------------------------------------------------------

def test_record_refuses_an_unfrozen_plan(run: Run, filled: Fill,
                                         project: Path) -> None:
    filled()
    sha = implement(project)
    code, _, err = run("record", "1", "TASK-1", "--sha", sha)
    assert code == 1 and "problem: plan 0001 is not frozen" in err


@pytest.mark.cross_os
def test_record_runs_the_tests_and_completes_the_item(run: Run,
                                                     filled: Fill, project: Path) -> None:
    filled()
    run("freeze", "1")
    sha = implement(project)
    code, out, err = run("record", "1", "TASK-1", "--sha", sha)
    assert code == 0, err
    item = read_plan(project)["items"][0]
    assert item["status"] == "COMPLETE" and item["verification_references"][0] == sha
    assert item["evidence"] == f"commit {sha[:7]}: 1 test node(s) passed"
    assert read_plan(project)["completed"] is not None
    pip = (project / PLANS / "0001_Add_subtraction_PIP.md").read_text(encoding="utf-8")
    assert "- [ ] " not in pip and "- [x] Test `tests/test_calc_sub.py::test_sub`" in pip
    assert out.startswith("record [done] | TASK-1 COMPLETE")
    assert run("check", "1")[0] == 0


@pytest.mark.cross_os
def test_record_runs_the_tests_at_the_commit_not_the_working_tree(run: Run, filled: Fill, project: Path,
                                                                  tmp_path: Path) -> None:
    filled()
    run("freeze", "1")
    source = project / PLANS / "0001" / "tests" / "tests" / "test_calc_sub.py"
    (project / "tests" / "test_calc_sub.py").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    calc = project / "src" / "calc.py"
    body = "\n\ndef sub(a, b):\n    from src.helper import minus\n    return minus(a, b)\n"
    calc.write_text(calc.read_text(encoding="utf-8") + body, encoding="utf-8")
    git(project, "add", "src/calc.py", "tests/test_calc_sub.py")
    git(project, "commit", "-q", "-m", "add sub on an uncommitted helper")
    sha = git(project, "rev-parse", "HEAD")
    (project / "src" / "helper.py").write_text("def minus(a, b):\n    return a - b\n", encoding="utf-8")
    code, _, err = run("record", "1", "TASK-1", "--sha", sha)
    assert code == 1 and f"problem: TASK-1 tests failed at {sha[:7]}" in err
    assert read_plan(project)["items"][0]["status"] == "PENDING" and trees(tmp_path) == []


def test_record_refuses_a_name_that_is_no_commit(run: Run, filled: Fill) -> None:
    filled()
    run("freeze", "1")
    code, _, err = run("record", "1", "TASK-1", "--sha", "deadbeef")
    assert code == 1 and "problem: deadbeef does not name a commit" in err


def test_record_refuses_a_commit_unreachable_from_head(run: Run, filled: Fill, project: Path) -> None:
    filled()
    run("freeze", "1")
    git(project, "checkout", "-q", "-b", "side")
    sha = implement(project)
    git(project, "checkout", "-q", "feat-x")
    code, _, err = run("record", "1", "TASK-1", "--sha", sha)
    assert code == 1 and f"problem: commit {sha[:7]} is not reachable from HEAD" in err


def test_record_start_and_blocked_set_their_states(run: Run, filled: Fill, project: Path) -> None:
    filled()
    run("freeze", "1")
    code, _, err = run("record", "1", "TASK-1", "--start")
    assert code == 0, err
    item = read_plan(project)["items"][0]
    assert item["status"] == "IN_PROGRESS" and item["evidence"].startswith("started ")
    code, out, err = run("record", "1", "TASK-1", "--blocked", "waits on the operator module")
    assert code == 0, err
    item = read_plan(project)["items"][0]
    assert item["status"] == "BLOCKED" and item["evidence"] == "waits on the operator module"
    assert out.startswith("record [done] | TASK-1 BLOCKED | open: TASK-1")


@pytest.mark.cross_os
def test_record_refuses_failing_tests(run: Run, filled: Fill,
                                     project: Path) -> None:
    filled()
    run("freeze", "1")
    implement(project)
    calc = project / "src" / "calc.py"
    calc.write_text(calc.read_text(encoding="utf-8").replace("a - b", "a + b"), encoding="utf-8")
    git(project, "commit", "-qam", "break sub")
    sha = git(project, "rev-parse", "HEAD")
    code, _, err = run("record", "1", "TASK-1", "--sha", sha)
    assert code == 1 and "problem: TASK-1 tests failed at" in err
    assert read_plan(project)["items"][0]["status"] == "PENDING"


def test_record_refuses_uncommitted_item_files(run: Run, filled: Fill,
                                              project: Path) -> None:
    filled()
    run("freeze", "1")
    sha = implement(project)
    (project / "src" / "calc.py").write_text("broken = 1\n", encoding="utf-8")
    code, _, err = run("record", "1", "TASK-1", "--sha", sha)
    assert code == 1 and "problem: TASK-1 files differ from" in err and "src/calc.py" in err


def test_record_refuses_a_commit_that_touches_no_item_file(run: Run,
                                                          filled: Fill,
                                                          project: Path) -> None:
    filled()
    run("freeze", "1")
    sha = git(project, "rev-parse", "HEAD")
    code, _, err = run("record", "1", "TASK-1", "--sha", sha)
    assert code == 1 and "problem: TASK-1: no file of the item changed between the base and" in err


def test_record_refuses_an_unmet_dependency(run: Run, filled: Fill,
                                           project: Path) -> None:
    filled()
    plan = read_plan(project)
    command = {"run": "python -m pytest tests/test_calc.py -q", "expect": "1 passed"}
    plan["items"].append({**sub_item(id="TASK-2", title="Docs", dependencies=["TASK-1"]),
                          "tests": [], "anchors": [], "commands": [command]})
    write_plan(project, plan)
    run("freeze", "1")
    sha = implement(project)
    code, _, err = run("record", "1", "TASK-2", "--sha", sha)
    assert code == 1 and "problem: TASK-2 depends on TASK-1, which is PENDING" in err


def test_record_closed_needs_no_commit(run: Run, filled: Fill,
                                      project: Path) -> None:
    filled()
    run("freeze", "1")
    reason = "superseded by the stdlib operator module"
    code, out, err = run("record", "1", "TASK-1", "--closed", reason)
    assert code == 0, err
    item = read_plan(project)["items"][0]
    assert item["status"] == "CLOSED_NO_ACTION" and item["evidence"] == reason


def test_record_start_after_completion_drops_completed_from_the_file(run: Run, filled: Fill,
                                                                    project: Path) -> None:
    filled()
    run("freeze", "1")
    run("record", "1", "TASK-1", "--closed", "superseded by the stdlib operator module")
    assert read_plan(project)["completed"] is not None
    code, _, err = run("record", "1", "TASK-1", "--start")
    assert code == 0, err
    assert "completed" not in read_plan(project)


# --- red --------------------------------------------------------------------------------------------------

def trees(tmp_path: Path) -> list:
    folder = tmp_path / "trees"
    return list(folder.iterdir()) if folder.is_dir() else []


@pytest.mark.cross_os
def test_red_passes_when_each_planned_test_fails_as_declared(run: Run, filled: Fill, project: Path,
                                                             tmp_path: Path) -> None:
    filled()
    code, out, err = run("red", "1")
    assert code == 0, err
    assert "TASK-1 tests/test_calc_sub.py::test_sub: ImportError (planned ImportError)" in out
    assert out.startswith("red [ok] | plan 0001 | 1 nodes fail as planned")
    assert trees(tmp_path) == [] and not (project / "tests" / "test_calc_sub.py").exists()


@pytest.mark.cross_os
def test_red_reports_a_test_that_fails_for_another_reason(run: Run, filled: Fill, tmp_path: Path) -> None:
    filled(sub_item(tests=[{"node": "tests/test_calc_sub.py::test_sub", "red": "AssertionError"}]))
    code, _, err = run("red", "1")
    assert code == 1 and "problem: red: TASK-1 tests/test_calc_sub.py::test_sub: expected AssertionError, " \
                         "got ImportError" in err
    assert trees(tmp_path) == []


@pytest.mark.cross_os
def test_freeze_refuses_a_planned_test_that_already_passes(run: Run, filled: Fill, project: Path) -> None:
    filled(sub_item(tests=[{"node": "tests/test_calc.py::test_add", "red": "AssertionError"}]))
    before = read_plan(project)
    code, _, err = run("freeze", "1")
    expected = "red: TASK-1 tests/test_calc.py::test_add: expected AssertionError, got PASSED"
    assert code == 1 and expected in err
    assert read_plan(project) == before


def test_red_with_no_tests_has_nothing_to_run(run: Run, filled: Fill) -> None:
    command = {"run": "python -m pytest tests/test_calc.py -q", "expect": "1 passed"}
    filled(sub_item(tests=[], commands=[command]))
    code, out, _ = run("red", "1")
    assert code == 0 and out.startswith("red [ok] | plan 0001 | no planned test nodes")


# --- lanes ------------------------------------------------------------------------------------------------

def test_lanes_needs_a_frozen_plan(run: Run, filled: Fill) -> None:
    filled()
    code, _, err = run("lanes", "1")
    assert code == 1 and "problem: plan 0001 is not frozen" in err


def test_lanes_prints_a_parallel2_plan_of_the_open_items(run: Run, filled: Fill) -> None:
    filled()
    run("freeze", "1")
    code, out, err = run("lanes", "1", "--target", "feat-x")
    assert code == 0, err
    lanes = json.loads(out)
    assert lanes["target"] == "feat-x"
    assert [(lane["id"], lane["wave"]) for lane in lanes["lanes"]] == [("task-1", 1)]
    assert lanes["lanes"][0]["files"] == ["src/calc.py", "tests/test_calc_sub.py"]


def test_lanes_maps_a_dotted_item_id_to_a_lane_id(run: Run, filled: Fill) -> None:
    filled(sub_item(id="TASK-1.2"))
    code, _, err = run("freeze", "1")
    assert code == 0, err
    code, out, err = run("lanes", "1", "--target", "feat-x")
    assert code == 0, err
    assert [lane["id"] for lane in json.loads(out)["lanes"]] == ["task-1-2"]
