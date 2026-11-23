"""The add-todo driver: ``add_todo.py row`` prints the ``harness:todo-editor`` dispatch row.

The research level picks the agent's model; ``--issue`` and the level reach the agent as header lines. The
note and the session's context never pass through the driver: the session appends them to the printed row.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _todo_helpers import CATALOG_REL, LEGACY_CATALOG, TODO_DIR, config, todo_files  # noqa: E402
from conftest import GIT_ENV, PLUGIN_ROOT  # noqa: E402
from harness_lib.add_todo_api import HOOK_REL, dispatch_row  # noqa: E402
from harness_lib.add_todo_models import AddTodoRequest, Closing, ResearchLevel, TodoHook  # noqa: E402

SCRIPT = PLUGIN_ROOT / "scripts" / "add_todo.py"


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_ENV}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(root), "row", *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


@pytest.mark.parametrize("level, model", [(0, "haiku"), (1, "sonnet"), (2, "opus"), (3, "opus")])
def test_each_level_picks_its_model(level: int, model: str) -> None:
    assert ResearchLevel(level).model == model


@pytest.mark.parametrize("level", [-1, 4])
def test_a_level_outside_zero_to_three_is_refused(level: int) -> None:
    with pytest.raises(ValidationError):
        AddTodoRequest(research=level)


def test_request_defaults_to_local_and_no_research() -> None:
    request = AddTodoRequest()
    assert (request.issue, request.research) == (False, ResearchLevel.NONE)


def test_row_lines(tmp_path: Path) -> None:
    assert dispatch_row(AddTodoRequest(issue=True, research=2), tmp_path) == [
        "agent=harness:todo-editor model=opus", "SKILL: add-todo", "Operation: add", "Issue: yes",
        "Research: 2", f"Project root: {tmp_path.resolve().as_posix()}"]


def _lines(done: subprocess.CompletedProcess) -> List[str]:
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()


def test_driver_prints_the_row(make_project) -> None:
    root = make_project(config(), files=todo_files())
    assert _lines(_run(root, "--issue", "-r", "1")) == dispatch_row(AddTodoRequest(issue=True, research=1),
                                                                   root)


def test_driver_defaults_to_a_local_reminder(make_project) -> None:
    root = make_project(config(), files=todo_files())
    lines = _lines(_run(root))
    assert lines[0] == "agent=harness:todo-editor model=haiku"
    assert "Issue: no" in lines and "Research: 0" in lines


def test_driver_takes_the_long_research_flag(make_project) -> None:
    root = make_project(config(), files=todo_files())
    assert "Research: 3" in _lines(_run(root, "--research", "3"))


def test_driver_refuses_without_a_todo_folder(make_project) -> None:
    root = make_project({})
    done = _run(root)
    assert done.returncode == 1
    assert done.stderr.startswith("problem:") and "todo.folder" in done.stderr


def test_driver_names_init_when_the_catalog_is_missing(make_project) -> None:
    root = make_project(config({"folder": TODO_DIR}))
    done = _run(root)
    assert done.returncode == 1
    assert done.stderr.startswith("problem:") and "todo_sync.py init" in done.stderr


def test_driver_refuses_a_bad_level(make_project) -> None:
    root = make_project(config(), files=todo_files())
    done = _run(root, "-r", "4")
    assert done.returncode == 2
    assert "research" in done.stderr


@pytest.mark.parametrize("extra", [["some note text"], ["--note", "some note text"]])
def test_driver_rejects_a_note_argument(make_project, extra: List[str]) -> None:
    root = make_project(config(), files=todo_files())
    done = _run(root, *extra)
    assert done.returncode == 2
    assert "unrecognized arguments" in done.stderr


def _hook(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_ENV}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(root), "hook", *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def _first_item(root: Path) -> dict:
    return json.loads((root / CATALOG_REL).read_text(encoding="utf-8"))["items"][0]


def test_the_goal_names_the_item_and_its_closing_clause() -> None:
    hook = TodoHook(closed_by=Closing.COMMITTED, desc="catalog item model", start_time=1.0,
                    todo_id="todo-af2e")
    assert hook.goal() == f"TODO todo-af2e (catalog item model) {Closing.COMMITTED.condition}"
    assert len(TodoHook(closed_by=Closing.RETIRED, desc="x" * 300, start_time=0, todo_id="t").goal()) <= 500


def test_a_hooked_row_carries_the_hook_line(make_project) -> None:
    root = make_project(config(), files=todo_files())
    assert _lines(_run(root, "--hook", "retired"))[-1] == "Hook: retired"


def test_an_unhooked_row_has_no_hook_line(make_project) -> None:
    root = make_project(config(), files=todo_files())
    assert not any(line.startswith("Hook:") for line in _lines(_run(root)))


def test_hook_arms_the_switch_for_a_catalog_item(make_project) -> None:
    root = make_project(config(), files=todo_files())
    item = _first_item(root)
    lines = _lines(_hook(root, "--todo", item["id"], "--closed-by", "developer"))
    assert lines[0].startswith(f"hook: armed {item['id']} (developer); goal: TODO {item['id']}")
    stored = json.loads((root / ".claude/state/harness" / HOOK_REL).read_text(encoding="utf-8"))
    assert stored["fired"] is None and stored["hook"]["todo_id"] == item["id"]
    assert stored["hook"]["goal"].endswith(Closing.DEVELOPER.condition)


def test_hook_refuses_an_unknown_id(make_project) -> None:
    done = _hook(make_project(config(), files=todo_files()), "--todo", "todo-zzzz", "--closed-by", "retired")
    assert done.returncode == 1 and "no catalog item todo-zzzz" in done.stderr


def test_hook_clear_removes_the_switch(make_project) -> None:
    root = make_project(config(), files=todo_files())
    _lines(_hook(root, "--todo", _first_item(root)["id"], "--closed-by", "retired"))
    assert _lines(_hook(root, "--clear")) == ["hook: cleared"]
    assert _lines(_hook(root, "--clear")) == ["hook: none"]


def test_driver_refuses_a_legacy_catalog_before_the_dispatch(make_project) -> None:
    files = todo_files()
    files[CATALOG_REL] = copy.deepcopy(LEGACY_CATALOG)
    done = _run(make_project(config(), files=files))
    assert done.returncode == 1 and done.stdout == ""
    assert done.stderr.startswith("problem: add-todo: ") and "migrate-ids" in done.stderr
