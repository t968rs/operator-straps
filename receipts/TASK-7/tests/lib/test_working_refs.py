"""Behavioral tests for ``harness_lib.working_refs`` and the plan's ``refs`` field (plan 2025, issue #301).

``working_refs`` parses the TODO ids and issue numbers a developer or a plan names, fills a TODO id's issues
from the catalog, and keeps the per-branch override file the working-refs mod reads.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

WALK_ROOTS = ()  # walks nothing; files live under tmp_path


def test_parse_refs_canonicalizes_todo_ids_and_issue_numbers() -> None:
    from harness_lib.working_refs import parse_refs
    refs = parse_refs(["TODO-K69M,#301", "315"])
    assert refs.todo_ids == ["todo-k69m"]
    assert refs.issues == [301, 315]


def test_parse_refs_drops_duplicates_keeping_the_first_order() -> None:
    from harness_lib.working_refs import parse_refs
    refs = parse_refs(["#301", "todo-k69m", "301", "K69M"])
    assert refs.todo_ids == ["todo-k69m"]
    assert refs.issues == [301]


def test_parse_refs_refuses_a_token_that_is_neither_an_id_nor_an_issue() -> None:
    from harness_lib.working_refs import WorkingRefsError, parse_refs
    with pytest.raises(WorkingRefsError):
        parse_refs(["banana!"])


def test_fill_issues_takes_gh_issues_from_the_catalog_when_none_are_named() -> None:
    from harness_lib.working_refs import fill_issues, parse_refs
    catalog = {"items": [{"id": "todo-k69m", "gh_issues": [301]}, {"id": "todo-v8mh", "gh_issues": [279]}]}
    assert fill_issues(parse_refs(["todo-k69m"]), catalog).issues == [301]


def test_fill_issues_keeps_named_issues_as_they_are() -> None:
    from harness_lib.working_refs import fill_issues, parse_refs
    catalog = {"items": [{"id": "todo-k69m", "gh_issues": [301]}]}
    assert fill_issues(parse_refs(["todo-k69m", "#315"]), catalog).issues == [315]


def test_set_override_keys_by_branch_and_clear_removes_only_that_branch(tmp_path: Path) -> None:
    from harness_lib.working_refs import (STORE_VERSION, clear_override, parse_refs, read_overrides,
                                          set_override)
    path = tmp_path / "working-refs" / "overrides.json"
    set_override(path, "1168-todo-banner", parse_refs(["todo-k69m", "#301"]))
    set_override(path, "main", parse_refs(["#1"]))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == STORE_VERSION
    entry = data["branches"]["1168-todo-banner"]
    assert (entry["todo_ids"], entry["issues"]) == (["todo-k69m"], [301])
    assert entry["set_at"].endswith("Z")
    assert clear_override(path, "1168-todo-banner") is True
    assert clear_override(path, "1168-todo-banner") is False
    assert sorted(read_overrides(path)) == ["main"]


def test_read_overrides_of_an_absent_file_is_empty(tmp_path: Path) -> None:
    from harness_lib.working_refs import read_overrides
    assert read_overrides(tmp_path / "absent.json") == {}


def test_a_plan_without_refs_dumps_no_refs_key() -> None:
    from harness_lib.plan_models import PlanRefs
    from harness_lib import plan_doc as pd
    raw = {"plan_id": "0001", "plan_created": "2026-11-17", "execution_model": "serial", "items": [],
           "base_commit": "0" * 40}
    assert "refs" not in pd.plan_dict(pd.validate_plan(raw))
    with_refs = pd.validate_plan({**raw, "refs": {"todo_ids": ["todo-k69m"], "issues": [301]}})
    assert with_refs.refs == PlanRefs(todo_ids=["todo-k69m"], issues=[301])
