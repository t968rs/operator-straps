"""Shared layout of the ``scripts/plan.py`` driver tests: the loaded driver, the project and its helpers.

Each test gets a project on branch ``feat-x`` cut from ``main``; red-run worktrees land in ``tmp_path/trees``.
The driver runs in-process through ``main`` with ``--repo``; the plan JSON and PIP are read back from disk.
Test modules import the ``driver``, ``project`` and ``run`` fixtures by name.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Tuple

import pytest
from conftest import git

from harness_lib import plan_doc as pd
from harness_lib import plan_record
from harness_lib.plan_enums import RecordScheme

WALK_ROOTS = ()  # walks only tmp_path/trees and a make_project repo
Result = Tuple[int, str, str]
Run = Callable[..., Result]
PLANS = "docs/PLANS"
SUB_TEST = "from src.calc import sub\n\n\ndef test_sub():\n    assert sub(3, 1) == 2\n"
MUL_TEST = "from src.calc import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n"
BASE_FILES = {
    "src/__init__.py": "",
    "src/calc.py": "def add(a, b):\n    return a + b\n",
    "tests/test_calc.py": "from src.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    "docs/spec.md": "# Spec\n\nAdd subtraction and multiplication.\n",
}


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
def sealed_first_freeze(monkeypatch: pytest.MonkeyPatch) -> None:
    """A first freeze stores the sealed scheme, as before receipts (D3), so the plan keeps its markdown PIP.

    Suites written for the sealed and legacy schemes bind it as an autouse fixture.
    """
    monkeypatch.setattr(plan_record, "FIRST_SCHEME", RecordScheme.sealed)


@pytest.fixture()
def project(make_project, tmp_path: Path) -> Path:
    """A project on ``feat-x``; red-run worktrees land in ``tmp_path/trees``."""
    config = {"base_branch": "main", "worktree_root": (tmp_path / "trees").as_posix()}
    root = make_project(config, files=BASE_FILES)
    git(root, "checkout", "-q", "-b", "feat-x")
    return root


@pytest.fixture()
def run(driver: ModuleType, project: Path, capsys: pytest.CaptureFixture) -> Run:
    """``run(*args, repo=project)`` -> (exit code, stdout, stderr) of ``plan.py --repo <repo> *args``."""
    def _run(*args: str, repo: Path = project) -> Result:
        code = driver.main(["--repo", str(repo), *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err
    return _run


def plan_file(root: Path) -> Path:
    return next((root / PLANS).glob("*_ActionPlan.json"))


def read_plan(root: Path) -> Dict[str, Any]:
    return json.loads(plan_file(root).read_text(encoding="utf-8"))


def write_plan(root: Path, plan: Dict[str, Any]) -> None:
    plan_file(root).write_text(json.dumps(plan, indent=2), encoding="utf-8")


def as_sealed(project: Path) -> None:
    """Restamp the frozen plan as frozen on the sealed scheme, the way a plan from before receipts looks."""
    plan = read_plan(project)
    plan["frozen"]["records"] = "sealed"
    write_plan(project, plan)
    plan["frozen"]["digest"] = pd.frozen_digest(pd.load_plan(plan_file(project)), RecordScheme.sealed)
    write_plan(project, plan)


def write_op(root: Path, name: str) -> None:
    """Write the ``name`` operator and its test into ``root`` (sub or mul)."""
    body = {"sub": "a - b", "mul": "a * b"}[name]
    test = {"sub": SUB_TEST, "mul": MUL_TEST}[name]
    (root / "tests" / f"test_calc_{name}.py").write_text(test, encoding="utf-8")
    calc = root / "src" / "calc.py"
    calc.write_text(calc.read_text(encoding="utf-8") + f"\n\ndef {name}(a, b):\n    return {body}\n",
                    encoding="utf-8")


def trees(tmp_path: Path) -> List[str]:
    """Names of the red-run worktrees left under ``tmp_path/trees``."""
    root = tmp_path / "trees"
    return sorted(p.name for p in root.iterdir()) if root.is_dir() else []
