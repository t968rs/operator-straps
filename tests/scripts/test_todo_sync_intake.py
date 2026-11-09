"""The ``init``, ``untracked`` and ``add`` subcommands of ``scripts/todo_sync.py``, run in-process with
``gh`` replaced.

Projects come from ``tests/lib/_todo_helpers.py`` (issues 11, 101, 102 and 103 are recorded in its catalog).
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _todo_helpers import CATALOG_REL, ID1, ID2, ID3, SNAP_DIR, build  # noqa: E402
from conftest import PLUGIN_ROOT  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, gh  # noqa: E402

UNTRACKED_REL = ".claude/state/harness/todo-sync/untracked.json"
NEW_ID = r"todo-[2-9a-hjkmnp-z]{4}"


@pytest.fixture(scope="module")
def driver():
    script = PLUGIN_ROOT / "scripts" / "todo_sync.py"
    spec = importlib.util.spec_from_file_location("todo_sync_driver", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _issue(number: int) -> Dict[str, Any]:
    return {"number": number, "title": f"Issue {number}", "labels": [], "body": "", "comments": [],
            "url": f"https://github.com/example/widgets/issues/{number}"}


def _open(monkeypatch, numbers: List[int]) -> None:
    monkeypatch.setattr(gh, "run_gh", lambda cwd, args: json.dumps([_issue(n) for n in numbers]))


def _spec(issue: int) -> Dict[str, Any]:
    return {"issue": issue, "url": f"https://github.com/example/widgets/issues/{issue}",
            "title": "New problem", "kind": "bug", "summary": "The parser skips a row.",
            "proposed_change": "Read every row.", "impact": "silent_wrong_output", "severity": 5,
            "why_ranked": "Computed from ranking_method.",
            "blast_radius": {"level": "S", "reasoning": "One module.", "consumers": []},
            "loe": {"size": "S", "reasoning": "Small."}}


def test_untracked_prints_the_issues_and_writes_the_file(driver, make_project, monkeypatch, capsys) -> None:
    root = build(make_project).project_root
    _open(monkeypatch, [11, 200])
    assert driver.main(["--project", str(root), "untracked"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "untracked: 1 open issue(s) in no catalog record"
    assert lines[1] == "#200 Issue 200"
    assert lines[2].startswith("wrote ") and lines[2].endswith("untracked.json")
    assert [r["number"] for r in json.loads((root / UNTRACKED_REL).read_text(encoding="utf-8"))] == [200]


def test_untracked_none_writes_nothing(driver, make_project, monkeypatch, capsys) -> None:
    root = build(make_project).project_root
    _open(monkeypatch, [11, 101])
    assert driver.main(["--project", str(root), "untracked"]) == 0
    assert capsys.readouterr().out.strip() == "untracked: none"
    assert not (root / UNTRACKED_REL).exists()


def test_untracked_exits_2_when_gh_fails(driver, make_project, monkeypatch, capsys) -> None:
    root = build(make_project).project_root

    def failing(cwd: Path, args) -> str:
        raise TodoSyncError("gh issue list failed: auth")

    monkeypatch.setattr(gh, "run_gh", failing)
    assert driver.main(["--project", str(root), "untracked"]) == 2
    assert "problem: gh issue list failed: auth" in capsys.readouterr().err
    assert not (root / UNTRACKED_REL).exists()


def test_untracked_reports_a_missing_catalog_before_gh(driver, make_project, monkeypatch, capsys) -> None:
    root = build(make_project, {}).project_root

    def forbidden(cwd: Path, args) -> str:
        raise AssertionError("gh was asked before the catalog was read")

    monkeypatch.setattr(gh, "run_gh", forbidden)
    assert driver.main(["--project", str(root), "untracked"]) == 2
    assert f"problem: {CATALOG_REL}: file not found" in capsys.readouterr().err


def test_untracked_needs_the_todo_folder(driver, make_project, capsys) -> None:
    root = make_project({}, files={})
    assert driver.main(["--project", str(root), "untracked"]) == 2
    assert "problem: untracked needs todo.folder" in capsys.readouterr().err


def test_init_creates_the_catalog_and_refuses_a_second_run(driver, make_project, capsys) -> None:
    root = build(make_project, {}).project_root
    assert driver.main(["--project", str(root), "init"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"created {CATALOG_REL}"
    assert lines[1].startswith(f"created {SNAP_DIR}/TODO_Snapshot_")
    assert lines[-1] == "next: todo_sync.py check, or /harness:sync-gh-todo to add the open issues"
    assert (root / CATALOG_REL).is_file()
    before = (root / CATALOG_REL).read_bytes()
    assert driver.main(["--project", str(root), "init"]) == 2
    assert "already exists" in capsys.readouterr().err
    assert (root / CATALOG_REL).read_bytes() == before


def test_add_prints_the_new_stable_id(driver, make_project, capsys) -> None:
    root = build(make_project).project_root
    spec = root / "add.json"
    spec.write_text(json.dumps({"items": [_spec(9)]}), encoding="utf-8")
    before = (root / CATALOG_REL).read_bytes()
    assert driver.main(["--project", str(root), "add", "--spec", str(spec), "--dry-run"]) == 0
    dry = capsys.readouterr().out
    assert re.search(rf"would add {NEW_ID} \(#9\)", dry)
    assert "note: new ids are drawn at random; the real run draws its own" in dry
    assert (root / CATALOG_REL).read_bytes() == before
    assert driver.main(["--project", str(root), "add", "--spec", str(spec)]) == 0
    out = capsys.readouterr().out
    found = re.search(rf"added ({NEW_ID}) \(#9\)", out)
    assert found, out
    items = json.loads((root / CATALOG_REL).read_text(encoding="utf-8"))["items"]
    assert [i["id"] for i in items] == [found.group(1), ID1, ID2, ID3]
    assert out.splitlines()[-1] == "next: todo_sync.py render, then todo_sync.py check"


def test_add_refusal_exits_2(driver, make_project, capsys) -> None:
    root = build(make_project).project_root
    spec = root / "add.json"
    spec.write_text(json.dumps({"items": [_spec(11)]}), encoding="utf-8")
    before = (root / CATALOG_REL).read_bytes()
    assert driver.main(["--project", str(root), "add", "--spec", str(spec)]) == 2
    assert "problem: issue #11 is already in the catalog" in capsys.readouterr().err
    assert (root / CATALOG_REL).read_bytes() == before
