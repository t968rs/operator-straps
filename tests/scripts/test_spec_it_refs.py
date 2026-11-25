"""The spec sheet driver's ``--refs``: ``spec_it.py check <path> --refs <ref> ...`` carries the TODO ids
and issue numbers the work answers onto the write-plan ``next:`` line, since the sheet itself holds none."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from conftest import GIT_ENV, PLUGIN_ROOT
from harness_lib.spec_it_models import SpecSheet, render_sheet

SCRIPT = PLUGIN_ROOT / "scripts" / "spec_it.py"
REL = "docs/SPECS/2026-11-25-brief.md"
NEXT = f'next: /harness:write-plan "Brief" --spec "{REL}"'


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_ENV}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def _project(make_project) -> Path:
    sheet = SpecSheet(title="Brief", day=date(2026, 11, 25), request="A short brief.",
                      goals=["Goal one holds."], avoid=["No second design document."])
    return make_project(config={}, files={REL: render_sheet(sheet)})


def _next_line(done: subprocess.CompletedProcess) -> str:
    return next(line for line in done.stdout.splitlines() if line.startswith("next: "))


def test_check_carries_refs_on_the_next_line(make_project) -> None:
    done = _run(_project(make_project), "check", REL, "--refs", "todo-k69m", "#301")
    assert done.returncode == 0, done.stderr
    assert _next_line(done) == f"{NEXT} --refs 'todo-k69m' '#301'"


def test_check_splits_comma_joined_refs(make_project) -> None:
    done = _run(_project(make_project), "check", REL, "--refs", "todo-k69m,#301")
    assert done.returncode == 0, done.stderr
    assert _next_line(done) == f"{NEXT} --refs 'todo-k69m' '#301'"


def test_check_drops_a_repeated_ref(make_project) -> None:
    done = _run(_project(make_project), "check", REL, "--refs", "#301", "todo-k69m", "#301")
    assert done.returncode == 0, done.stderr
    assert _next_line(done) == f"{NEXT} --refs '#301' 'todo-k69m'"


def test_check_refuses_a_ref_that_is_neither_a_todo_id_nor_an_issue(make_project) -> None:
    done = _run(_project(make_project), "check", REL, "--refs", "todo-k69m", "TASK-2")
    assert done.returncode == 1
    assert done.stdout == ""
    assert done.stderr.startswith("problem: ") and "TASK-2" in done.stderr
