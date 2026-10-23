"""Review links in issue text and the review text fetched for them, with the ``gh api`` calls replaced."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import build  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, gh, issues  # noqa: E402
from harness_lib.todo_sync.reviews import ReviewLink, fetch_reviews, review_links, slug_of  # noqa: E402

SLUG = "example/widgets"
PR7 = f"https://github.com/{SLUG}/pull/7#pullrequestreview-55"
BASE = f"repos/{SLUG}/pulls"


def _fake_api(monkeypatch, objects: Dict[str, Any], lists: Dict[str, List[Any]]) -> List[str]:
    asked: List[str] = []

    def obj(cwd: Path, path: str) -> Any:
        asked.append(path)
        return objects[path]

    def rows(cwd: Path, path: str) -> List[Any]:
        asked.append(path)
        return lists.get(path, [])

    monkeypatch.setattr(gh, "api_object", obj)
    monkeypatch.setattr(gh, "api_list", rows)
    return asked


def _fake_api_lists(monkeypatch, lists: Dict[str, List[Any]]) -> None:
    monkeypatch.setattr(gh, "api_list", lambda cwd, path: lists.get(path, []))


def _review(state: str = "COMMENTED", body: str = "", login: str = "ann", **over: Any) -> Dict[str, Any]:
    return {"state": state, "body": body, "user": {"login": login}, **over}


def test_review_links_keep_only_this_repository() -> None:
    text = (f"see {PR7} and https://github.com/{SLUG}/pull/8 again {PR7}, "
            "not https://github.com/other/thing/pull/9#pullrequestreview-1")
    assert review_links([text], SLUG) == [ReviewLink(7, 55), ReviewLink(8, None)]


def test_slug_of_reads_owner_and_repo() -> None:
    assert slug_of("https://github.com/example/widgets/issues/3") == SLUG
    assert slug_of("https://example.com/x") == ""


def test_named_review_returns_body_and_inline_comments(monkeypatch) -> None:
    comment = {"path": "src/a.py", "line": 12, "body": "Rename this", "user": {"login": "ann"}}
    _fake_api(monkeypatch, {f"{BASE}/7/reviews/55": _review(body="Overall notes")},
              {f"{BASE}/7/reviews/55/comments": [comment]})
    found, truncated, errors = fetch_reviews(Path("."), SLUG, [ReviewLink(7, 55)])
    assert truncated is False and errors == []
    assert found == [{"source": PR7, "state": "COMMENTED", "author": "ann", "body": "Overall notes",
                      "comments": [{"path": "src/a.py", "line": 12, "author": "ann", "body": "Rename this"}]}]


def test_bare_pr_reads_every_review_and_skips_dismissed_and_blank(monkeypatch) -> None:
    listed = [_review("DISMISSED", "old", id=1), _review(id=2), _review(body="Please fix", id=3)]
    asked = _fake_api(monkeypatch, {}, {f"{BASE}/8/reviews": listed})
    found, _, _ = fetch_reviews(Path("."), SLUG, [ReviewLink(8, None)])
    assert [r["source"] for r in found] == [f"https://github.com/{SLUG}/pull/8#pullrequestreview-3"]
    assert f"{BASE}/8/reviews/1/comments" not in asked


def test_budget_truncates_and_flags(monkeypatch) -> None:
    listed = [_review(body="a" * 30, id=1), _review(body="b" * 30, id=2)]
    _fake_api(monkeypatch, {}, {f"{BASE}/8/reviews": listed})
    found, truncated, _ = fetch_reviews(Path("."), SLUG, [ReviewLink(8, None)], budget=40)
    assert [r["body"][0] for r in found] == ["a"]
    assert truncated is True


def test_failed_review_fetch_is_reported_not_fatal(monkeypatch) -> None:
    def gone(cwd: Path, path: str) -> Any:
        raise TodoSyncError(f"gh api {path} failed: HTTP 404")

    monkeypatch.setattr(gh, "api_object", gone)
    _fake_api_lists(monkeypatch, {f"{BASE}/8/reviews": [_review(body="Please fix", id=3)]})
    found, truncated, errors = fetch_reviews(Path("."), SLUG, [ReviewLink(7, 55), ReviewLink(8, None)])
    assert [r["source"][-1] for r in found] == ["3"]
    assert len(errors) == 1 and PR7 in errors[0] and "HTTP 404" in errors[0]


def test_api_failures_name_the_endpoint(monkeypatch) -> None:
    failed = subprocess.CompletedProcess(["gh"], 1, stdout="", stderr="HTTP 404")
    monkeypatch.setattr(gh.subprocess, "run", lambda *a, **k: failed)
    with pytest.raises(TodoSyncError, match=f"{BASE}/5/reviews"):
        gh.api_list(Path("."), f"{BASE}/5/reviews")


def test_find_untracked_attaches_linked_reviews(make_project, monkeypatch) -> None:
    linked = {"number": 200, "title": "Doc updates", "labels": [], "comments": [],
              "url": f"https://github.com/{SLUG}/issues/200", "body": f"resolve the points in {PR7}"}
    plain = {**linked, "number": 201, "body": "no link"}
    monkeypatch.setattr(gh, "run_gh", lambda cwd, args: json.dumps([linked, plain]))
    _fake_api(monkeypatch, {f"{BASE}/7/reviews/55": _review(body="Overall notes")}, {})
    rows = {r["number"]: r for r in issues.find_untracked(build(make_project))}
    assert len(rows[200]["reviews"]) == 1 and rows[200]["reviews_truncated"] is False
    assert rows[201]["reviews"] == [] and rows[201]["review_errors"] == []


def test_a_dead_review_link_leaves_the_issue_listed(make_project, monkeypatch) -> None:
    dead = {"number": 200, "title": "Doc updates", "labels": [], "comments": [],
            "url": f"https://github.com/{SLUG}/issues/200", "body": f"see {PR7}"}
    monkeypatch.setattr(gh, "run_gh", lambda cwd, args: json.dumps([dead]))

    def gone(cwd: Path, path: str) -> Any:
        raise TodoSyncError(f"gh api {path} failed: HTTP 404")

    monkeypatch.setattr(gh, "api_object", gone)
    rows = issues.find_untracked(build(make_project))
    assert [r["number"] for r in rows] == [200]
    assert rows[0]["reviews"] == [] and len(rows[0]["review_errors"]) == 1
