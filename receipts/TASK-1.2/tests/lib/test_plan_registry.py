"""``plan_registry``: a plan's planned registry entries and the project's upsert command (issue 346).

The entries live at ``<plans dir>/<plan_id>/registry_entries.json`` as ``{"plan": <id>, "entries": [...]}``,
each entry a registry entry dump with a ``file``. The configured ``tests.planned_registry`` argv writes them
into a registry; ``{registry}`` and ``{entries}`` become the registry path and a JSON file of the entries.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from harness_lib import plan_registry as preg
from harness_lib.plan_doc import PlanError
from harness_lib.plan_models import ActionPlan

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _plan_driver_helpers import UPSERT  # noqa: E402

WALK_ROOTS = ()


def plan(*nodes: str) -> ActionPlan:
    tests = [{"node": node, "red": "ImportError"} for node in nodes]
    return ActionPlan.model_validate({
        "plan_id": "0001", "plan_created": "2026-11-24", "execution_model": "serial", "base_commit": "e" * 40,
        "items": [{"id": "TASK-1", "title": "Add sub", "action": "Add sub.", "status": "PENDING",
                   "evidence": "not started", "files": ["src/calc.py"], "tests": tests}],
    })


def write_entries(plans: Path, entries: List[Dict[str, Any]], plan_id: str = "0001") -> Path:
    path = preg.entries_path(plans, "0001")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"plan": plan_id, "entries": entries}), encoding="utf-8")
    return path


def write_registry(path: Path, files: List[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tests": [{"file": f} for f in files]}), encoding="utf-8")
    return path


def plant(plans: Path, rel: str) -> None:
    source = plans / "0001" / "tests" / rel
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def test_x():\n    pass\n", encoding="utf-8")


# --- the entries file -------------------------------------------------------------------------------------

def test_the_entries_file_sits_in_the_plan_folder(tmp_path: Path) -> None:
    assert preg.entries_path(tmp_path, "0001") == tmp_path / "0001" / "registry_entries.json"


def test_no_entries_file_loads_as_none(tmp_path: Path) -> None:
    assert preg.load_entries(tmp_path, "0001") is None


def test_entries_load_with_their_files(tmp_path: Path) -> None:
    write_entries(tmp_path, [{"file": "tests/test_a.py", "properties": {"slow": False}}])
    loaded = preg.load_entries(tmp_path, "0001")
    assert loaded is not None and loaded.files() == ["tests/test_a.py"]
    assert loaded.entries[0]["properties"] == {"slow": False}


@pytest.mark.parametrize("entries, plan_id, words", [
    ([{"name": "a"}], "0001", "file"),
    ([{"file": ""}], "0001", "file"),
    ([{"file": "tests/test_a.py"}, {"file": "tests/test_a.py"}], "0001", "twice"),
    ([{"file": "tests/test_a.py"}], "0002", "plan 0002"),
])
def test_a_bad_entries_file_is_a_problem(tmp_path: Path, entries: List[Dict[str, Any]], plan_id: str,
                                          words: str) -> None:
    write_entries(tmp_path, entries, plan_id)
    with pytest.raises(PlanError) as raised:
        preg.load_entries(tmp_path, "0001")
    assert any("0001/registry_entries.json" in p and words in p for p in raised.value.problems)


def test_an_unreadable_entries_file_is_a_problem(tmp_path: Path) -> None:
    path = preg.entries_path(tmp_path, "0001")
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(PlanError, match="registry_entries.json"):
        preg.load_entries(tmp_path, "0001")


# --- the registry -----------------------------------------------------------------------------------------

def test_registered_reads_the_files_of_the_tests_list(tmp_path: Path) -> None:
    registry = write_registry(tmp_path / "registry.json", ["tests/test_a.py", "tests/test_b.py"])
    assert preg.registered(registry) == {"tests/test_a.py", "tests/test_b.py"}
    assert preg.registered(tmp_path / "missing.json") == set()


def test_pending_skips_files_already_registered_and_files_not_asked_for(tmp_path: Path) -> None:
    write_entries(tmp_path, [{"file": "tests/test_a.py"}, {"file": "tests/test_b.py"},
                             {"file": "tests/test_c.py"}])
    registry = write_registry(tmp_path / "registry.json", ["tests/test_a.py"])
    loaded = preg.load_entries(tmp_path, "0001")
    assert loaded is not None
    found = preg.pending(loaded, ["tests/test_b.py", "tests/test_a.py"], registry)
    assert found == [{"file": "tests/test_b.py"}]


# --- the upsert command -----------------------------------------------------------------------------------

def test_the_placeholders_become_the_registry_and_the_entries_paths(tmp_path: Path) -> None:
    argv = preg.command_argv(("python", "reg.py", "--registry={registry}", "{entries}"),
                             tmp_path / "r.json", tmp_path / "e.json")
    assert argv == ["python", "reg.py", f"--registry={tmp_path / 'r.json'}", str(tmp_path / "e.json")]


def test_upsert_runs_the_command_with_the_entries(tmp_path: Path) -> None:
    (tmp_path / "reg.py").write_text(UPSERT, encoding="utf-8")
    registry = write_registry(tmp_path / "tests" / "registry.json", ["tests/test_a.py"])
    command = (sys.executable, "reg.py", "{registry}", "{entries}")
    preg.upsert(command, registry, [{"file": "tests/test_b.py", "slow": True}], tmp_path)
    data = json.loads(registry.read_text(encoding="utf-8"))
    assert data["tests"] == [{"file": "tests/test_a.py"}, {"file": "tests/test_b.py", "slow": True}]


def test_a_failed_upsert_is_a_problem_with_the_output_tail(tmp_path: Path) -> None:
    (tmp_path / "reg.py").write_text("import sys\nprint('no such registry')\nsys.exit(3)\n", encoding="utf-8")
    command = (sys.executable, "reg.py", "{registry}", "{entries}")
    with pytest.raises(PlanError) as raised:
        preg.upsert(command, tmp_path / "registry.json", [{"file": "tests/test_b.py"}], tmp_path)
    text = "\n".join(raised.value.problems)
    assert "planned_registry" in text and "exit 3" in text and "no such registry" in text


def test_an_upsert_that_exits_0_without_writing_is_a_problem(tmp_path: Path) -> None:
    (tmp_path / "reg.py").write_text("print('wrote somewhere else')\n", encoding="utf-8")
    registry = write_registry(tmp_path / "tests" / "registry.json", ["tests/test_a.py"])
    command = (sys.executable, "reg.py", "{registry}", "{entries}")
    with pytest.raises(PlanError) as raised:
        preg.upsert(command, registry, [{"file": "tests/test_a.py"}, {"file": "tests/test_b.py"}], tmp_path)
    assert raised.value.problems == [
        "tests/test_b.py: tests.planned_registry exited 0 but the registry does not list it"]


def test_a_relative_program_joins_the_working_folder(tmp_path: Path) -> None:
    assert preg._program("bin/tool", tmp_path) == str(tmp_path / "bin/tool")


def test_a_bare_program_name_runs_from_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "reg.py").write_text(UPSERT, encoding="utf-8")
    registry = write_registry(tmp_path / "tests" / "registry.json", [])
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    command = (Path(sys.executable).name, "reg.py", "{registry}", "{entries}")
    preg.upsert(command, registry, [{"file": "tests/test_b.py"}], tmp_path)
    assert preg.registered(registry) == {"tests/test_b.py"}


@pytest.mark.parametrize("program", ["no-such-upsert-tool", "bin/no-such-upsert-tool"])
def test_a_program_that_does_not_exist_is_a_problem(tmp_path: Path, program: str) -> None:
    command = (program, "{registry}", "{entries}")
    with pytest.raises(PlanError) as raised:
        preg.upsert(command, tmp_path / "registry.json", [{"file": "tests/test_b.py"}], tmp_path)
    assert raised.value.problems[0].startswith(f"tests.planned_registry: {program} ")


# --- lint -------------------------------------------------------------------------------------------------

def test_lint_names_a_planned_test_with_no_entry(tmp_path: Path) -> None:
    plans, repo = tmp_path / "plans", tmp_path / "repo"
    plant(plans, "tests/test_a.py")
    write_registry(repo / "tests" / "registry.json", [])
    problems = preg.lint_problems(plan("tests/test_a.py::test_x"), plans, repo, "tests/registry.json", True)
    assert problems == ["registry: tests/test_a.py is planned with no entry in 0001/registry_entries.json"]


def test_lint_accepts_a_planned_test_already_registered(tmp_path: Path) -> None:
    plans, repo = tmp_path / "plans", tmp_path / "repo"
    plant(plans, "tests/test_a.py")
    write_registry(repo / "tests" / "registry.json", ["tests/test_a.py"])
    assert preg.lint_problems(plan("tests/test_a.py::test_x"), plans, repo, "tests/registry.json", True) == []


def test_lint_skips_the_missing_entry_rule_without_the_key(tmp_path: Path) -> None:
    plans, repo = tmp_path / "plans", tmp_path / "repo"
    plant(plans, "tests/test_a.py")
    write_registry(repo / "tests" / "registry.json", [])
    problems = preg.lint_problems(plan("tests/test_a.py::test_x"), plans, repo, "tests/registry.json", False)
    assert problems == []


def test_lint_names_an_entry_for_a_file_neither_planned_nor_present(tmp_path: Path) -> None:
    plans, repo = tmp_path / "plans", tmp_path / "repo"
    plant(plans, "tests/test_a.py")
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_b.py").write_text("", encoding="utf-8")
    write_entries(plans, [{"file": "tests/test_a.py"}, {"file": "tests/test_b.py"},
                          {"file": "tests/test_gone.py"}])
    problems = preg.lint_problems(plan("tests/test_a.py::test_x"), plans, repo, None, False)
    assert problems == ["registry: entry tests/test_gone.py in 0001/registry_entries.json names no planned "
                        "or present file"]


def test_lint_reports_a_bad_entries_file(tmp_path: Path) -> None:
    plans, repo = tmp_path / "plans", tmp_path / "repo"
    write_entries(plans, [{"name": "a"}])
    problems = preg.lint_problems(plan(), plans, repo, None, False)
    assert len(problems) == 1 and problems[0].startswith("registry: 0001/registry_entries.json")
