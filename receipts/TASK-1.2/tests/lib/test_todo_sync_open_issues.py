"""The open-issue list ``todo_sync.py untracked`` leaves for the working-refs mod, with ``gh`` replaced.

``find_untracked`` already lists every open issue; it also writes their numbers to
``<state_dir>/todo-sync/open_issues.json`` so the mod can hide closed issues without a ``gh`` call of its own.
A listing cut off at the limit writes nothing, since an issue missing from it may still be open.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import build  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, gh, issues  # noqa: E402


def _issue(number: int) -> Dict[str, Any]:
    return {"number": number, "title": f"Issue {number}", "labels": [], "body": "", "comments": [],
            "url": f"https://github.com/example/widgets/issues/{number}"}


def _fake_gh(monkeypatch, rows: List[Dict[str, Any]]) -> None:
    monkeypatch.setattr(gh, "run_gh", lambda cwd, args: json.dumps(rows))


def test_the_path_sits_under_state_dir(make_project) -> None:
    cfg = build(make_project)
    path = issues.open_issues_path(cfg)
    assert path == cfg.path(cfg.state_dir) / issues.OPEN_ISSUES_REL
    assert issues.OPEN_ISSUES_REL == "todo-sync/open_issues.json"


def test_find_untracked_writes_every_open_issue_number(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    _fake_gh(monkeypatch, [_issue(300), _issue(11), _issue(200)])
    issues.find_untracked(cfg)
    data = json.loads(issues.open_issues_path(cfg).read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["open"] == [11, 200, 300]
    assert datetime.strptime(data["fetched_at"], "%Y-%m-%dT%H:%M:%SZ")


def test_the_list_is_written_when_nothing_is_untracked(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    _fake_gh(monkeypatch, [_issue(11)])
    assert issues.find_untracked(cfg) == []
    assert json.loads(issues.open_issues_path(cfg).read_text(encoding="utf-8"))["open"] == [11]


def test_a_listing_at_the_limit_writes_no_list(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    monkeypatch.setattr(issues, "LIST_LIMIT", 2)
    _fake_gh(monkeypatch, [_issue(1), _issue(2)])
    with pytest.raises(TodoSyncError):
        issues.find_untracked(cfg)
    assert not issues.open_issues_path(cfg).exists()
