"""A malformed exclusions file: exit 1 with one ``problem:`` line from scripts/diff_delta.py and pr_sum.py.

Each test builds a throwaway project with ``make_project`` whose configured exclusions file
(``config/ex.json``) is broken. ``diff_delta.py`` runs by path with the current interpreter; ``pr_sum.py`` is
imported by path and its ``build`` command is replaced by one that reads the shared pattern lookup
(``harness_lib.diff_delta.active_patterns``), the read ``PrFile.artifact`` makes. The strict lookup
pr-review uses (``review_plan.exclusion_patterns``) raises the same ``DeltaError``.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable, Iterator

import pytest

from conftest import PLUGIN_ROOT
from harness_lib import diff_delta, review_plan
from harness_lib.config import activate, load_config

_DIFF_DELTA = PLUGIN_ROOT / "scripts" / "diff_delta.py"
_PR_SUM = PLUGIN_ROOT / "scripts" / "pr_sum.py"
_BROKEN = ["{not json", '{"no_exclusions": []}', '{"exclusions": [{"reason": "no pattern"}]}']


@pytest.fixture(scope="module")
def pr_sum() -> Iterator[ModuleType]:
    """Import pr_sum.py by absolute path, registered in ``sys.modules`` so dataclass annotations resolve."""
    spec = importlib.util.spec_from_file_location("pr_sum_malformed_exclusions", _PR_SUM)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _project(make_project: Callable[..., Path], body: str) -> Path:
    return make_project(config={"exclusions": "config/ex.json"}, files={"config/ex.json": body})


@pytest.mark.parametrize("body", _BROKEN)
def test_diff_delta_reports_one_problem_line(make_project: Callable[..., Path], body: str) -> None:
    root = _project(make_project, body)
    done = subprocess.run([sys.executable, str(_DIFF_DELTA), "HEAD", "HEAD", "--repo", str(root)],
                          cwd=str(root), capture_output=True, text=True)
    assert done.returncode == 1
    assert done.stdout == ""
    lines = done.stderr.splitlines()
    assert len(lines) == 1 and lines[0].startswith("problem: ") and "ex.json" in lines[0]


@pytest.mark.parametrize("body", _BROKEN)
def test_pr_sum_reports_one_problem_line(
        pr_sum: ModuleType, make_project: Callable[..., Path], monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture, body: str,
) -> None:
    monkeypatch.chdir(_project(make_project, body))
    monkeypatch.setattr(pr_sum, "_cmd_build", lambda args, root: len(diff_delta.active_patterns()))
    assert pr_sum.main(["build", "x.json"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("problem: ") and "Traceback" not in err and len(err.splitlines()) == 1


@pytest.mark.parametrize("body", _BROKEN)
def test_review_plan_lookup_raises_delta_error(make_project: Callable[..., Path], body: str) -> None:
    root = _project(make_project, body)
    activate(load_config(root))
    with pytest.raises(diff_delta.DeltaError):
        review_plan.exclusion_patterns(root)
