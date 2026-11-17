"""The add-todo driver: ``add_todo.py row`` prints the ``harness:todo-editor`` dispatch row.

The research level picks the agent's model; ``--issue`` and the level reach the agent as header lines. The
note and the session's context never pass through the driver: the session appends them to the printed row.
"""
from __future__ import annotations

import copy
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
from harness_lib.add_todo_api import dispatch_row  # noqa: E402
from harness_lib.add_todo_models import AddTodoRequest, ResearchLevel  # noqa: E402

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


def test_driver_refuses_a_legacy_catalog_before_the_dispatch(make_project) -> None:
    files = todo_files()
    files[CATALOG_REL] = copy.deepcopy(LEGACY_CATALOG)
    done = _run(make_project(config(), files=files))
    assert done.returncode == 1 and done.stdout == ""
    assert done.stderr.startswith("problem: add-todo: ") and "migrate-ids" in done.stderr
