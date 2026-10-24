"""Open-issue listing and tracked-number coverage for ``todo_sync.py untracked``, with ``gh`` replaced.

The shared project (``_todo_helpers``) records issues 11 (item source), 101 (tracker), 103 (tracker child) and
102 (close candidate, research entry); every other open issue is untracked.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, RESEARCH_REL, TODO_DIR, build, config, todo_files  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, gh, issues  # noqa: E402
from harness_lib.todo_sync.sources import Sources  # noqa: E402


def _issue(number: int, **over: Any) -> Dict[str, Any]:
    base = {"number": number, "title": f"Issue {number}", "labels": [], "body": "", "comments": [],
            "url": f"https://github.com/example/widgets/issues/{number}"}
    return {**base, **over}


def _fake_gh(monkeypatch, open_issues: List[Dict[str, Any]]) -> List[List[str]]:
    calls: List[List[str]] = []

    def fake(cwd: Path, args) -> str:
        calls.append(list(args))
        return json.dumps(open_issues)

    monkeypatch.setattr(gh, "run_gh", fake)
    return calls


def test_tracked_numbers_cover_every_record(make_project) -> None:
    cfg = build(make_project)
    assert issues.tracked_numbers(Sources(cfg)) == {11, 101, 102, 103}


@pytest.mark.parametrize("item, number", [
    ({"gh_issues": [301]}, 301),
    ({"sources": [{"type": "gh_issue", "ref": "303"}]}, 303),
], ids=["gh_issues", "gh_issue_source"])
def test_each_item_field_alone_tracks_its_number(make_project, item, number) -> None:
    files = todo_files()
    files[CATALOG_REL]["items"] = [{"id": "solo", **item}]
    cfg = build(make_project, files)
    assert number in issues.tracked_numbers(Sources(cfg))


def test_an_issue_only_cross_referenced_by_an_item_is_untracked(make_project) -> None:
    files = todo_files()
    files[CATALOG_REL]["items"] = [{"id": "solo", "related_gh_issues": [302]}]
    cfg = build(make_project, files)
    assert 302 not in issues.tracked_numbers(Sources(cfg))


def test_research_entry_issues_count_as_tracked(make_project) -> None:
    files = todo_files()
    files[RESEARCH_REL]["entries"][0]["issues"] = ["205", 206]
    cfg = build(make_project, files)
    assert {205, 206} <= issues.tracked_numbers(Sources(cfg))


def test_tracked_numbers_without_a_research_catalog(make_project) -> None:
    files = todo_files()
    del files[RESEARCH_REL]
    cfg = build(make_project, files)
    assert cfg.todo.research.catalog is None
    assert issues.tracked_numbers(Sources(cfg)) == {11, 101, 102, 103}


def test_find_untracked_lists_only_unrecorded_issues(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    fresh = _issue(200, labels=[{"name": "bug"}], body=None,
                   comments=[{"author": {"login": "ann"}, "body": "hi"}])
    _fake_gh(monkeypatch, [_issue(11), _issue(101), _issue(102), _issue(103), fresh])
    rows = issues.find_untracked(cfg)
    assert [r["number"] for r in rows] == [200]
    assert rows[0]["labels"] == ["bug"]
    assert rows[0]["body"] == ""
    assert rows[0]["comments"] == [{"author": "ann", "body": "hi"}]
    assert rows[0]["reviews"] == [] and rows[0]["reviews_truncated"] is False


def test_find_untracked_sorts_rows_by_number(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    _fake_gh(monkeypatch, [_issue(300), _issue(101), _issue(200)])
    assert [r["number"] for r in issues.find_untracked(cfg)] == [200, 300]


def test_open_issues_ask_for_every_open_issue(make_project, monkeypatch) -> None:
    calls = _fake_gh(monkeypatch, [])
    issues.open_issues(build(make_project))
    args = calls[0]
    assert args[:2] == ["issue", "list"]
    assert args[args.index("--state") + 1] == "open"
    assert args[args.index("--limit") + 1] == "1000"
    assert "--repo" not in args
    repo_cfg = build(make_project, cfg=config(todo={"folder": TODO_DIR, "gh": {"repo": "example/widgets"}}))
    issues.open_issues(repo_cfg)
    assert calls[1][calls[1].index("--repo") + 1] == "example/widgets"


def test_run_gh_reports_failure_and_missing_gh(monkeypatch) -> None:
    failed = subprocess.CompletedProcess(["gh"], 1, stdout="", stderr="auth")
    monkeypatch.setattr(gh.subprocess, "run", lambda *a, **k: failed)
    with pytest.raises(TodoSyncError) as exc:
        gh.run_gh(Path("."), ["issue", "list", "--state", "open"])
    assert "gh issue list failed" in str(exc.value) and "auth" in str(exc.value)

    def missing(*a, **k):
        raise OSError("not found")

    monkeypatch.setattr(gh.subprocess, "run", missing)
    with pytest.raises(TodoSyncError, match="gh could not run"):
        gh.run_gh(Path("."), ["issue", "list"])


def test_write_untracked_lands_under_state_dir(make_project) -> None:
    cfg = build(make_project)
    rows = [{"number": 200, "title": "Issue 200"}]
    path = issues.write_untracked(cfg, rows)
    assert path == issues.untracked_path(cfg)
    assert path.relative_to(cfg.project_root).as_posix() == ".claude/state/harness/todo-sync/untracked.json"
    assert json.loads(path.read_text(encoding="utf-8")) == rows
