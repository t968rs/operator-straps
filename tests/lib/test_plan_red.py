"""Tests of ``harness_lib.plan_red``: planned tests overlaid on the plan's base commit and run red."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from conftest import git

from harness_lib import plan_red as pr

MIX = """\
FFFF.F                                                                   [100%]
================================== FAILURES ===================================
_________________________________ test_assert _________________________________

    def test_assert():
>       assert 1 == 2
E       assert 1 == 2

tests\\test_mix.py:6: AssertionError
_________________________________ test_import _________________________________

    def test_import():
>       import not_a_module_xyz  # noqa: F401
E       ModuleNotFoundError: No module named 'not_a_module_xyz'

tests\\test_mix.py:10: ModuleNotFoundError
_________________________________ test_nested _________________________________

    def test_nested():
>       helper()

tests\\test_mix.py:14:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    def helper():
>       raise NotImplementedError("later")
E       NotImplementedError: later

tests\\test_mix.py:2: NotImplementedError
__________________________________ test_attr __________________________________

    def test_attr():
        import os
>       os.nope
E       AttributeError: module 'os' has no attribute 'nope'

tests\\test_mix.py:19: AttributeError
__________________________________ test_type __________________________________

    def test_type():
>       len(3)
E       TypeError: object of type 'int' has no len()

tests\\test_mix.py:27: TypeError
=========================== short test summary info ===========================
FAILED tests/test_mix.py::test_assert - assert 1 == 2
FAILED tests/test_mix.py::test_import - ModuleNotFoundError: No module named ...
FAILED tests/test_mix.py::test_nested - NotImplementedError: later
FAILED tests/test_mix.py::test_attr - AttributeError: module 'os' has no attr...
FAILED tests/test_mix.py::test_type - TypeError: object of type 'int' has no ...
5 failed, 1 passed in 0.07s
"""

PASS = ".                                                                        [100%]\n1 passed in 0.01s\n"

CLASS_FAIL = """\
F                                                                        [100%]
================================== FAILURES ===================================
_______________________________ TestQ.test_c[1] _______________________________

self = <test_q.TestQ object at 0x0>

>   raise KeyError("k")
E   KeyError: 'k'

tests\\test_q.py:4: KeyError
1 failed in 0.02s
"""

COLLECT_IMPORT = """\

=================================== ERRORS ====================================
__________________ ERROR collecting tests/test_modimport.py ___________________
ImportError while importing test module 'C:\\r\\tests\\test_modimport.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
tests\\test_modimport.py:1: in <module>
    from not_a_module_abc import thing
E   ModuleNotFoundError: No module named 'not_a_module_abc'
=========================== short test summary info ===========================
ERROR tests/test_modimport.py
1 error in 0.06s
ERROR: not found: C:\\r\\tests\\test_modimport.py::test_x
(no name 'C:\\\\r\\\\tests\\\\test_modimport.py::test_x' in any of [<Module tests/test_modimport.py>])
"""

COLLECT_SYNTAX = """\

=================================== ERRORS ====================================
____________________ ERROR collecting tests/test_syntax.py ____________________
..\\ast.py:50: in parse
    return compile(source, filename, mode, flags,
E     File "C:\\r\\tests\\test_syntax.py", line 1
E       def test_x(:
E                  ^
E   SyntaxError: invalid syntax
=========================== short test summary info ===========================
ERROR tests/test_syntax.py
1 error in 0.18s
ERROR: not found: C:\\r\\tests\\test_syntax.py::test_x
"""

CONFTEST = """\
ImportError while loading conftest 'C:\\r\\tests\\conftest.py'.
tests\\conftest.py:1: in <module>
    import nothing_here
E   ModuleNotFoundError: No module named 'nothing_here'
"""

NOT_FOUND = """\

no tests ran in 0.01s
ERROR: not found: C:\\r\\tests\\test_mix.py::test_nope
(no name 'C:\\\\r\\\\tests\\\\test_mix.py::test_nope' in any of [<Module tests/test_mix.py>])
"""

NO_FILE = "\nno tests ran in 0.00s\nERROR: file or directory not found: tests/test_gone.py::test_x\n"


# --- classify ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("node", "expected"), [
    ("tests/test_mix.py::test_assert", "AssertionError"),
    ("tests/test_mix.py::test_import", "ImportError"),
    ("tests/test_mix.py::test_nested", "NotImplementedError"),
    ("tests/test_mix.py::test_attr", "AttributeError"),
    ("tests/test_mix.py::test_type", "TypeError"),
    ("tests/test_mix.py::test_pass", "PASSED"),
])
def test_classify_finds_the_node_in_a_run_of_several(node: str, expected: str) -> None:
    assert pr.classify(MIX, node) == expected


@pytest.mark.parametrize(("output", "node", "expected"), [
    (PASS, "tests/test_x.py::test_x", "PASSED"),
    (COLLECT_IMPORT, "tests/test_modimport.py::test_x", "ImportError"),
    (COLLECT_SYNTAX, "tests/test_syntax.py::test_x", "COLLECTION"),
    (CONFTEST, "tests/test_x.py::test_x", "COLLECTION"),
    (NOT_FOUND, "tests/test_mix.py::test_nope", "MISSING"),
    (NO_FILE, "tests/test_gone.py::test_x", "MISSING"),
    ("", "tests/test_x.py::test_x", "MISSING"),
])
def test_classify_single_node_outputs(output: str, node: str, expected: str) -> None:
    assert pr.classify(output, node) == expected


def test_classify_ignores_a_collection_error_of_another_file() -> None:
    assert pr.classify(COLLECT_IMPORT + PASS, "tests/test_x.py::test_x") == "PASSED"


def test_classify_falls_back_to_the_only_failure_of_a_single_node_run() -> None:
    assert pr.classify(CLASS_FAIL, "sub/test_q.py::test_renamed") == "KeyError"


def test_classify_a_class_method_with_parameters() -> None:
    assert pr.classify(CLASS_FAIL, "tests/test_q.py::TestQ::test_c[1]") == "KeyError"


# --- red problems -----------------------------------------------------------------------------------------

def test_red_problems_name_each_mismatch() -> None:
    results = [
        pr.RedResult("TASK-1", "tests/x.py::test_a", "ImportError", "ImportError"),
        pr.RedResult("TASK-1", "tests/x.py::test_y", "ImportError", "PASSED"),
        pr.RedResult("TASK-2", "tests/z.py::test_z", "TypeError", "AssertionError"),
    ]
    assert pr.red_problems(results) == [
        "TASK-1 tests/x.py::test_y: expected ImportError, got PASSED",
        "TASK-2 tests/z.py::test_z: expected TypeError, got AssertionError",
    ]


@pytest.mark.parametrize("got", ["PASSED", "COLLECTION", "MISSING"])
def test_red_problems_never_accept_a_non_exception(got: str) -> None:
    assert len(pr.red_problems([pr.RedResult("T", "t.py::t", got, got)])) == 1


# --- sources and overlay ----------------------------------------------------------------------------------

def plan(*items: Dict[str, Any]) -> Dict[str, Any]:
    return {"plan_id": "0007", "base_commit": "", "items": list(items)}


def item(ident: str, nodes: Dict[str, str], status: str = "PENDING") -> Dict[str, Any]:
    tests = [{"node": node, "red": red} for node, red in nodes.items()]
    return {"id": ident, "title": ident, "status": status, "files": ["src/calc.py"], "tests": tests}


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_test_sources_map_planned_files_of_open_items(tmp_path: Path) -> None:
    plans = tmp_path / "PLANS"
    new = write(plans, "0007/tests/tests/test_new.py", "x\n")
    write(plans, "0007/tests/tests/test_done.py", "x\n")
    data = plan(
        item("TASK-1", {"tests/test_new.py::test_a": "ImportError", "tests/test_new.py::test_b": "TypeError",
                        "tests/test_old.py::test_c": "AssertionError"}),
        item("TASK-2", {"tests/test_done.py::test_d": "ImportError"}, status="COMPLETE"),
    )
    assert pr.test_sources(data, plans) == {"tests/test_new.py": new}


def test_overlay_copies_sources_into_the_tree(tmp_path: Path) -> None:
    first = write(tmp_path / "src", "a.py", "one\n")
    second = write(tmp_path / "src", "b.py", "two\n")
    tree = tmp_path / "tree"
    write(tree, "tests/test_b.py", "old\n")
    written = pr.overlay({"tests/deep/test_a.py": first, "tests/test_b.py": second}, tree)
    assert written == ["tests/deep/test_a.py", "tests/test_b.py"]
    assert (tree / "tests" / "deep" / "test_a.py").read_text(encoding="utf-8") == "one\n"
    assert (tree / "tests" / "test_b.py").read_text(encoding="utf-8") == "two\n"


# --- worktree lifecycle and an end-to-end red run ---------------------------------------------------------

BASE = {
    "calc.py": "def add(a, b):\n    return a + b\n",
    "tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
}
PLANNED = "from calc_ext import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n"


@pytest.mark.cross_os
def test_make_tree_and_drop_tree(make_project, tmp_path: Path) -> None:
    repo = make_project(files=BASE)
    base = git(repo, "rev-parse", "HEAD")
    tree = pr.make_tree(repo, base, tmp_path / "trees")
    assert tree.parent == tmp_path / "trees"
    assert git(tree, "rev-parse", "HEAD") == base and git(tree, "branch", "--show-current") == ""
    assert pr.make_tree(repo, base, tmp_path / "trees") != tree
    pr.drop_tree(repo, tree)
    assert not tree.exists()


@pytest.mark.cross_os
def test_run_red_classifies_every_open_node_in_the_tree(make_project, tmp_path: Path) -> None:
    repo = make_project(files=BASE)
    plans = tmp_path / "PLANS"
    write(plans, "0007/tests/tests/test_mul.py", PLANNED)
    data = plan(
        item("TASK-1", {"tests/test_mul.py::test_mul": "ImportError"}),
        item("TASK-2", {"tests/test_calc.py::test_add": "AssertionError"}),
        item("TASK-3", {"tests/test_calc.py::test_add": "TypeError"}, status="COMPLETE"),
    )
    tree = pr.make_tree(repo, git(repo, "rev-parse", "HEAD"), tmp_path / "trees")
    try:
        assert pr.overlay(pr.test_sources(data, plans), tree) == ["tests/test_mul.py"]
        results = pr.run_red(data, tree, sys.executable)
    finally:
        pr.drop_tree(repo, tree)
    assert results == [
        pr.RedResult("TASK-1", "tests/test_mul.py::test_mul", "ImportError", "ImportError"),
        pr.RedResult("TASK-2", "tests/test_calc.py::test_add", "AssertionError", "PASSED"),
    ]
    assert pr.red_problems(results) == [
        "TASK-2 tests/test_calc.py::test_add: expected AssertionError, got PASSED",
    ]
    assert not (repo / "tests" / "test_mul.py").exists()


def test_run_red_runs_one_node_per_pytest_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[List[str]] = []

    def fake(args: List[str], cwd: Path) -> str:
        calls.append(list(args))
        return PASS

    monkeypatch.setattr(pr, "pytest_output", fake)
    data = plan(item("TASK-1", {"tests/a.py::t1": "ImportError", "tests/a.py::t2": "ImportError"}))
    pr.run_red(data, tmp_path, "py")
    assert calls == [["py", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/a.py::t1"],
                     ["py", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/a.py::t2"]]
