"""``plan.py`` and a plan's planned registry entries (issue 346).

The project registers its test files in ``tests/registry.json`` and its conftest ends a pytest session that
names an unregistered test file, as a consumer's registry plugin does. ``tests.planned_registry`` runs
``scripts/reg.py`` to upsert entries. The plan keeps the entry of its planned test in
``<plans>/0001/registry_entries.json``; ``red`` applies it in the throwaway tree only, ``register`` writes it
into the live registry once the item copied the test, and ``record`` names entries still pending.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pytest
from conftest import git

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_driver_helpers import (  # noqa: E402
    BASE_FILES, PLANS, SUB_TEST, UPSERT, Run, read_plan, trees, write_op, write_plan,
)

driver, run = helpers.driver, helpers.run
WALK_ROOTS = ()  # walks only a make_project repo and tmp_path/trees
SUB = "tests/test_calc_sub.py"
ENTRY = {"file": SUB, "kind": "unit"}
GATE = (
    "import json\n"
    "from pathlib import Path\n\n"
    "import pytest\n\n"
    "ROOT = Path(__file__).resolve().parent.parent\n\n\n"
    "def pytest_sessionstart(session):\n"
    "    files = {e['file'] for e in json.loads((ROOT / 'tests' / 'registry.json').read_text())['tests']}\n"
    "    for arg in session.config.args:\n"
    "        rel = arg.split('::', 1)[0].replace('\\\\', '/')\n"
    "        if Path(rel).name.startswith('test_') and rel not in files:\n"
    "            pytest.exit(f'unregistered test file {rel}', returncode=4)\n"
)
REGISTRY = {"tests": [{"file": "tests/test_calc.py", "kind": "unit"}]}
Fill = Callable[..., Dict[str, Any]]


def config(tmp_path: Path, keyed: bool = True) -> Dict[str, Any]:
    tests: Dict[str, Any] = {"registry": "tests/registry.json"}
    if keyed:
        tests["planned_registry"] = [sys.executable, "scripts/reg.py", "{registry}", "{entries}"]
    return {"base_branch": "main", "worktree_root": (tmp_path / "trees").as_posix(), "tests": tests,
            "review": {"registry_guards": ["tests/test_registry_guard.py"]}}


def build(make_project, tmp_path: Path, keyed: bool = True) -> Path:
    files = {**BASE_FILES, "tests/registry.json": REGISTRY, "scripts/reg.py": UPSERT,
             "tests/conftest.py": GATE}
    root = make_project(config(tmp_path, keyed), files=files)
    git(root, "checkout", "-q", "-b", "feat-x")
    return root


@pytest.fixture()
def project(make_project, tmp_path: Path) -> Path:
    return build(make_project, tmp_path)


@pytest.fixture()
def filled(run: Run, project: Path) -> Fill:
    """``filled(entries=True)``: ``new``, one item with a planned test and, when asked, its planned entry."""
    def _fill(entries: Optional[bool] = True) -> Dict[str, Any]:
        code, _, err = run("new", "Add subtraction", "--spec", "docs/spec.md")
        assert code == 0, err
        folder = project / PLANS / "0001"
        planned = folder / "tests" / SUB
        planned.parent.mkdir(parents=True, exist_ok=True)
        planned.write_text(SUB_TEST, encoding="utf-8")
        if entries:
            (folder / "registry_entries.json").write_text(json.dumps({"plan": "0001", "entries": [ENTRY]}),
                                                          encoding="utf-8")
        plan = read_plan(project)
        plan["items"] = [{"id": "TASK-1", "title": "Add subtraction", "action": "Add sub beside add.",
                          "status": "PENDING", "evidence": "not started", "files": ["src/calc.py", SUB],
                          "tests": [{"node": f"{SUB}::test_sub", "red": "ImportError"}]}]
        write_plan(project, plan)
        return plan
    return _fill


def live_files(project: Path) -> list:
    return [e["file"] for e in json.loads((project / "tests" / "registry.json").read_text())["tests"]]


# --- red --------------------------------------------------------------------------------------------------

@pytest.mark.cross_os
def test_red_applies_the_planned_entry_in_the_tree_only(run: Run, filled: Fill, project: Path,
                                                         tmp_path: Path) -> None:
    filled()
    code, out, err = run("red", "1")
    assert code == 0, err
    assert f"TASK-1 {SUB}::test_sub: ImportError (planned ImportError)" in out
    assert live_files(project) == ["tests/test_calc.py"] and trees(tmp_path) == []


@pytest.mark.cross_os
def test_red_without_the_planned_entry_meets_the_registry_gate(run: Run, filled: Fill) -> None:
    filled(entries=False)
    code, _, err = run("red", "1")
    assert code == 1 and f"problem: red: TASK-1 {SUB}::test_sub: expected ImportError, got MISSING" in err


# --- check ------------------------------------------------------------------------------------------------

def test_check_names_a_planned_test_with_no_entry(run: Run, filled: Fill) -> None:
    filled(entries=False)
    code, _, err = run("check", "1")
    expected = f"problem: registry: {SUB} is planned with no entry in 0001/registry_entries.json"
    assert code == 1 and expected in err


def test_check_passes_with_the_entry(run: Run, filled: Fill) -> None:
    filled()
    code, out, err = run("check", "1")
    assert code == 0, err
    assert out.startswith("check [ok]")


# --- freeze -----------------------------------------------------------------------------------------------

@pytest.mark.cross_os
def test_freeze_carries_the_entries_file_in_its_tree(run: Run, filled: Fill, project: Path) -> None:
    filled()
    code, _, err = run("freeze", "1")
    assert code == 0, err
    entry = json.loads(helpers.freeze_entry_file(project).read_text(encoding="utf-8"))
    assert f"{PLANS}/0001/registry_entries.json" in entry["files"]


# --- register ---------------------------------------------------------------------------------------------

def test_register_refuses_a_test_not_copied_yet(run: Run, filled: Fill, project: Path) -> None:
    filled()
    code, _, err = run("register", "1", "TASK-1")
    expected = f"problem: {SUB} is not in the tree yet; copy it from {PLANS}/0001/tests/{SUB}"
    assert code == 1 and expected in err
    assert live_files(project) == ["tests/test_calc.py"]


def test_register_writes_the_entry_and_names_the_guards(run: Run, filled: Fill, project: Path) -> None:
    filled()
    write_op(project, "sub")
    code, out, err = run("register", "1", "TASK-1")
    assert code == 0, err
    assert out.splitlines()[0] == "register [done] | TASK-1 | 1 entry written"
    assert f"registered: {SUB}" in out and "guard: tests/test_registry_guard.py" in out
    assert live_files(project) == ["tests/test_calc.py", SUB]
    code, out, err = run("register", "1", "TASK-1")
    assert code == 0, err
    assert out.splitlines()[0] == "register [done] | TASK-1 | 0 entries written"
    assert f"skipped: {SUB} (already registered)" in out


def test_register_refuses_a_test_with_no_entry(run: Run, filled: Fill, project: Path) -> None:
    filled(entries=False)
    write_op(project, "sub")
    code, _, err = run("register", "1", "TASK-1")
    expected = f"problem: {SUB} has no planned entry in 0001/registry_entries.json and the registry does not"
    assert code == 1 and f"{expected} list it" in err
    assert live_files(project) == ["tests/test_calc.py"]


def test_register_needs_the_key(run: Run, make_project, tmp_path: Path) -> None:
    root = build(make_project, tmp_path, keyed=False)
    code, _, _ = run("new", "Add subtraction", "--spec", "docs/spec.md", repo=root)
    assert code == 0
    code, _, err = run("register", "1", "TASK-1", repo=root)
    assert code == 1 and "problem: tests.planned_registry is not set" in err


# --- record -----------------------------------------------------------------------------------------------

@pytest.mark.cross_os
def test_record_names_an_entry_still_pending(run: Run, filled: Fill, project: Path) -> None:
    filled()
    code, _, err = run("freeze", "1")
    assert code == 0, err
    code, out, err = run("record", "1", "TASK-1", "--start")
    assert code == 0, err
    hint = f"pending entry: {SUB} (plan.py register 0001 TASK-1)"
    assert f"{hint} after copying it from {PLANS}/0001/tests/{SUB}" in out
    write_op(project, "sub")
    code, _, err = run("register", "1", "TASK-1")
    assert code == 0, err
    code, out, err = run("record", "1", "TASK-1", "--start")
    assert code == 0, err
    assert "pending entry:" not in out
