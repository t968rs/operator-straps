"""``plan.py new --refs``: a plan's structured TODO ids and issue numbers (plan 2025, issue #301).

The working-refs mod reads ``refs`` from the ActionPlan JSON beside a written plan page; the ids are
canonicalized as todo_sync does, and a TODO id given with no issue takes its ``gh_issues`` from the catalog.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_driver_helpers import Run, read_plan  # noqa: E402

driver, project, run = helpers.driver, helpers.project, helpers.run  # the shared fixtures, by name
WALK_ROOTS = ()  # walks only a make_project repo


def _new(run: Run, *extra: str):
    """``plan.py new`` with ``extra``; an argparse refusal of an unknown option fails the test plainly."""
    try:
        return run("new", "Add subtraction", *extra)
    except SystemExit as exc:
        raise AssertionError(f"plan.py new refused its arguments (exit {exc.code})") from exc


def _with_catalog(project: Path) -> None:
    """Point ``todo.folder`` at ``docs/TODO`` and write a catalog that maps todo-k69m to issue 301."""
    config_file = project / ".claude" / "harness.json"
    config = json.loads(config_file.read_text(encoding="utf-8"))
    config_file.write_text(json.dumps({**config, "todo": {"folder": "docs/TODO"}}), encoding="utf-8")
    folder = project / "docs" / "TODO"
    folder.mkdir(parents=True)
    catalog = {"items": [{"id": "todo-k69m", "gh_issues": [301]}]}
    (folder / "RepoToDo.json").write_text(json.dumps(catalog), encoding="utf-8")


def test_new_stores_canonical_refs(run: Run, project: Path) -> None:
    code, _, err = _new(run, "--refs", "TODO-K69M,#301")
    assert code == 0, err
    assert read_plan(project)["refs"] == {"todo_ids": ["todo-k69m"], "issues": [301]}


def test_new_fills_issues_from_the_todo_catalog(run: Run, project: Path) -> None:
    _with_catalog(project)
    code, _, err = _new(run, "--refs", "todo-k69m")
    assert code == 0, err
    assert read_plan(project)["refs"] == {"todo_ids": ["todo-k69m"], "issues": [301]}


def test_new_refuses_a_bad_ref_with_a_problem_line(run: Run) -> None:
    code, _, err = _new(run, "--refs", "banana!")
    assert code == 1
    assert err.startswith("problem:")
