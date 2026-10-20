"""Retiring finished TODO items: removal, renumbering, id rewrites and counts, on copies of
``TodoCatalog.min.json`` (TODO-001 unblocks TODO-002; TODO-002 sits under tracker #101 and names #102)."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, MIN_CATALOG, build, rule_findings, todo_files  # noqa: E402
from harness_lib.todo_sync import TodoSyncError  # noqa: E402
from harness_lib.todo_sync.retire import normalize_id, retire_items  # noqa: E402

CATALOG_RULES = ["T1", "T6", "T7", "T8", "T9", "T10"]


def _catalog():
    return copy.deepcopy(MIN_CATALOG)


def _ids(catalog):
    return [i["id"] for i in catalog["items"]]


def _assert_clean(make_project, catalog) -> None:
    files = todo_files()
    files[CATALOG_REL] = catalog
    cfg = build(make_project, files)
    for rule in CATALOG_RULES:
        assert rule_findings(cfg, rule) == [], rule


@pytest.mark.parametrize("raw", ["TODO-001", "todo-001", "TODO-1", "1", "001", " 01 "])
def test_normalize_id_accepts_short_forms(raw: str) -> None:
    assert normalize_id(raw) == "TODO-001"


@pytest.mark.parametrize("raw", ["", "TODO-", "x1", "0", "TODO-0"])
def test_normalize_id_rejects_garbage(raw: str) -> None:
    with pytest.raises(TodoSyncError):
        normalize_id(raw)


def test_unknown_id_is_refused() -> None:
    with pytest.raises(TodoSyncError, match="TODO-009"):
        retire_items(_catalog(), ["TODO-009"])


def test_input_catalog_is_not_mutated() -> None:
    catalog = _catalog()
    retire_items(catalog, ["TODO-001"])
    assert catalog == MIN_CATALOG


def test_retiring_the_last_item_renames_nothing(make_project) -> None:
    out = retire_items(_catalog(), ["TODO-003"])
    assert _ids(out.catalog) == ["TODO-001", "TODO-002"]
    assert out.renames == {}
    assert [i["id"] for i in out.retired] == ["TODO-003"]
    _assert_clean(make_project, out.catalog)


def test_retiring_the_first_item_renumbers_and_rewrites_links(make_project) -> None:
    catalog = _catalog()
    catalog["items"][2]["summary"] = "Waits on the decision noted in TODO-003 itself."
    out = retire_items(catalog, ["TODO-001"])
    assert out.renames == {"TODO-002": "TODO-001", "TODO-003": "TODO-002"}
    items = out.catalog["items"]
    assert [(i["id"], i["rank"]) for i in items] == [("TODO-001", 1), ("TODO-002", 2)]
    assert items[0]["depends_on"] == []
    assert items[1]["summary"] == "Waits on the decision noted in TODO-002 itself."
    assert out.catalog["trackers"][0]["child_todo_ids"] == ["TODO-001"]
    assert out.catalog["close_candidates"][0]["related_todo_ids"] == ["TODO-001"]
    _assert_clean(make_project, out.catalog)


def test_losing_the_only_unblocked_item_drops_the_bonus(make_project) -> None:
    before = MIN_CATALOG["items"][0]["priority"]
    assert before["components"]["unblock_bonus"] > 0
    out = retire_items(_catalog(), ["TODO-002"])
    first = next(i for i in out.catalog["items"] if i["title"] == MIN_CATALOG["items"][0]["title"])
    assert first["unblocks"] == []
    assert first["priority"]["components"]["unblock_bonus"] == 0
    assert first["priority"]["score"] < before["score"]
    _assert_clean(make_project, out.catalog)


def test_a_retired_child_leaves_trackers_and_close_candidates(make_project) -> None:
    out = retire_items(_catalog(), ["TODO-002"])
    assert out.renames == {"TODO-003": "TODO-002"}
    assert out.catalog["trackers"][0]["child_todo_ids"] == []
    assert out.catalog["close_candidates"][0]["related_todo_ids"] == []
    _assert_clean(make_project, out.catalog)


def test_counts_follow_the_items_and_keep_zero_keys() -> None:
    out = retire_items(_catalog(), ["TODO-001"])
    counts = out.catalog["counts"]
    assert counts["items"] == 2
    assert counts["by_status"] == {"NEEDS_DECISION": 1, "OPEN": 0, "PARTIAL": 1}
    assert counts["by_loe"]["XL"] == 0
    assert list(counts["by_loe"]) == list(MIN_CATALOG["counts"]["by_loe"])
    assert counts["sources_absorbed"]["gh_issue"] == MIN_CATALOG["counts"]["sources_absorbed"]["gh_issue"] - 1


def test_a_retired_id_left_in_prose_is_reported_not_rewritten() -> None:
    catalog = _catalog()
    catalog["items"][1]["summary"] = "Picks up after TODO-001 lands."
    out = retire_items(catalog, ["TODO-001"])
    assert out.catalog["items"][0]["summary"] == "Picks up after TODO-001 lands."
    assert out.dangling == ("items/TODO-001/summary names retired TODO-001",)


def test_report_names_open_issues_and_touched_trackers() -> None:
    out = retire_items(_catalog(), ["TODO-001", "TODO-002"])
    assert out.issues_to_close == (11,)
    assert out.trackers_touched == (101,)


def test_an_issue_already_listed_as_close_candidate_is_not_repeated() -> None:
    catalog = _catalog()
    catalog["items"][0]["gh_issues"] = [102]
    out = retire_items(catalog, ["TODO-001"])
    assert out.issues_to_close == ()
