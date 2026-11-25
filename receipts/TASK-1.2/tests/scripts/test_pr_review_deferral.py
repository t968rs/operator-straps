"""Deferral bookkeeping of the plugin's scripts/pr_review.py: timing rows normalized to registry paths,
deferrals saved in ``waves.json`` outliving a replaced timing report, and shell-quoted pytest commands.

The script is loaded by absolute path from the plugin. Each test builds a bare project with
``make_project`` and activates its config directly.
"""
from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, Iterator, List

import pytest

from harness_lib.config import activate, load_config

_SCRIPT = Path("scripts") / "pr_review.py"
_TESTS = {"registry": "tests/registry.json", "timings": "reports/timings.json",
          "fixer_test_seconds": 60, "defer_flags": ["properties.super_slow"]}
_CONFIG = {"base_branch": "dev", "artifacts": {"scratch": "build/review_runs"}, "tests": _TESTS}
_REGISTRY = {"tests": [
    {"file": "tests/test_a.py", "properties": {"test_target_paths": ["src/pkg/a.py"]}},
    {"file": "tests/test_slow.py", "properties": {"test_target_paths": ["src/pkg/"]}},
]}
_SLOW = {"tests": [{"file": "tests/test_a.py", "duration": 0.5},
                   {"file": "tests/test_slow.py", "duration": 90.0}]}


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> Iterator[ModuleType]:
    """Import pr_review.py by absolute path, registered in ``sys.modules`` so annotations resolve."""
    spec = importlib.util.spec_from_file_location("pr_review_deferral_under_test", plugin_root / _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _project(make_project, timings: object) -> Path:
    """A bare project with the two-entry registry and ``timings`` as its report, config activated."""
    repo = make_project(_CONFIG, {"tests/registry.json": _REGISTRY, "reports/timings.json": timings})
    activate(load_config(repo))
    return repo


@pytest.mark.parametrize("name", ["tests/test_slow.py::test_one", "tests\\test_slow.py",
                                  "./tests/test_slow.py", ".\\tests\\test_slow.py::test_one"])
def test_timing_rows_match_the_registry_path(script: ModuleType, make_project, name: str) -> None:
    rows: List[Dict[str, object]] = [{"file": name, "duration": 50.0}, {"file": name, "duration": 40.0}]
    repo = _project(make_project, {"tests": rows})
    assert script.file_seconds(repo) == {"tests/test_slow.py": 90.0}
    assert script.defer_reasons(repo) == {"tests/test_slow.py": "measured 90 s > 60 s"}


def test_saved_deferral_outlives_a_replaced_timing_report(
        script: ModuleType, make_project, tmp_path: Path,
) -> None:
    repo, run = _project(make_project, _SLOW), tmp_path / "run"
    run.mkdir()
    store = {"waves": [], "deferred": script.run_deferrals(repo, run)}
    (run / "waves.json").write_text(json.dumps(store), encoding="utf-8")
    replaced = {"tests": [{"file": "tests/test_a.py", "duration": 0.5}]}
    (repo / "reports" / "timings.json").write_text(json.dumps(replaced), encoding="utf-8")
    assert script.defer_reasons(repo) == {}
    reasons = script.run_deferrals(repo, run)
    assert reasons == {"tests/test_slow.py": "measured 90 s > 60 s"}
    lines = script.deferred_lines(repo, reasons, {"src/pkg/a.py"})
    assert "  - tests/test_slow.py (measured 90 s > 60 s)" in lines
    assert "tests/test_slow.py" in lines[-1] and "tests/test_a.py" not in lines[-1]


def test_pytest_command_quotes_each_test_path(script: ModuleType) -> None:
    command = script.pytest_command("/tmp/my project", ["tests/test_a.py", "tests/test_b.py"])
    args = shlex.split(command)
    assert "/tmp/my project/tests/test_a.py" in args and "/tmp/my project/tests/test_b.py" in args
    plain = script.pytest_command("C:/repo", ["tests/test_a.py"])
    assert " C:/repo/tests/test_a.py " in plain
