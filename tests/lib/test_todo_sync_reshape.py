"""Splitting one TODO item into parts and refreshing the ranking, on copies of ``TodoCatalog.min.json``
(TODO-001 unblocks TODO-002; TODO-002 sits under tracker #101 and names close candidate #102)."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, MIN_CATALOG, build, rule_findings, todo_files  # noqa: E402
from harness_lib.todo_sync import TodoSyncError  # noqa: E402
from harness_lib.todo_sync.reshape import refresh_items, split_item  # noqa: E402

CATALOG_RULES = ["T1", "T6", "T7", "T8", "T9", "T10"]


def _catalog():
    return copy.deepcopy(MIN_CATALOG)


def _by_id(catalog):
    return {i["id"]: i for i in catalog["items"]}


def _assert_clean(make_project, catalog) -> None:
    files = todo_files()
    files[CATALOG_REL] = catalog
    cfg = build(make_project, files)
    for rule in CATALOG_RULES:
        assert rule_findings(cfg, rule) == [], rule


def _loader_parts():
    """TODO-002 split in two: the XS part outranks the inherited M part."""
    return [
        {"title": "Split the loader reads", "loe": {"size": "XS", "reasoning": "One function."}},
        {"title": "Split the loader writes"},
    ]


def test_split_inherits_links_tracker_and_close_candidates(make_project) -> None:
    out = split_item(_catalog(), "2", _loader_parts())
    items = _by_id(out.catalog)
    assert [i["id"] for i in out.catalog["items"]] == ["TODO-001", "TODO-002", "TODO-003", "TODO-004"]
    assert out.parts == ("TODO-002", "TODO-003")
    assert items["TODO-002"]["title"] == "Split the loader reads"
    assert items["TODO-003"]["title"] == "Split the loader writes"
    assert out.renames == {"TODO-003": "TODO-004"}
    assert items["TODO-001"]["unblocks"] == ["TODO-002", "TODO-003"]
    assert items["TODO-002"]["depends_on"] == ["TODO-001"] == items["TODO-003"]["depends_on"]
    assert out.catalog["trackers"][0]["child_todo_ids"] == ["TODO-002", "TODO-003"]
    assert out.catalog["close_candidates"][0]["related_todo_ids"] == ["TODO-002", "TODO-003"]
    assert items["TODO-002"]["priority"]["score"] == 1.4606
    assert out.catalog["counts"]["items"] == 4
    _assert_clean(make_project, out.catalog)


def test_split_prose_naming_the_original_follows_the_first_part(make_project) -> None:
    catalog = _catalog()
    catalog["items"][2]["summary"] = "After TODO-001 lands; see TODO-002 too."
    parts = [{"title": "Parser drops the last row on CRLF input", "severity": 3},
             {"title": "Parser drops the last row on LF input"}]
    out = split_item(catalog, "TODO-001", parts)
    items = _by_id(out.catalog)
    assert out.parts == ("TODO-002", "TODO-001")
    assert out.renames == {"TODO-002": "TODO-003", "TODO-003": "TODO-004"}
    assert items["TODO-004"]["summary"] == "After TODO-002 lands; see TODO-003 too."
    assert out.flagged == ("items/TODO-004/summary names split TODO-001, now TODO-002 (first part)",)
    assert items["TODO-003"]["depends_on"] == ["TODO-001", "TODO-002"]
    _assert_clean(make_project, out.catalog)


def test_split_does_not_mutate_its_input() -> None:
    catalog = _catalog()
    split_item(catalog, "2", _loader_parts())
    assert catalog == MIN_CATALOG


@pytest.mark.parametrize(("parts", "message"), [
    ([{"title": "Only one"}], "at least two parts"),
    ([{"title": "A", "id": "TODO-009"}, {"title": "B"}], "sets id"),
    ([{"title": "A", "priority": {}}, {"title": "B"}], "sets priority"),
    ([{"summary": "no title"}, {"title": "B"}], "needs a title"),
    ([{"title": "Same"}, {"title": "Same"}], "share the title"),
    ([{"title": "A", "unblocks": ["TODO-009"]}, {"title": "B"}], "TODO-009"),
    ([{"title": "A", "unblocks": ["TODO-002"]}, {"title": "B"}], "names the item being split"),
    (["not an object", {"title": "B"}], "not an object"),
])
def test_split_refuses_a_bad_spec(parts, message: str) -> None:
    with pytest.raises(TodoSyncError, match=message):
        split_item(_catalog(), "2", parts)


def test_split_unknown_id_is_refused() -> None:
    with pytest.raises(TodoSyncError, match="TODO-009"):
        split_item(_catalog(), "9", _loader_parts())


def test_refresh_of_a_ranked_catalog_changes_nothing() -> None:
    out = refresh_items(_catalog())
    assert out.catalog == MIN_CATALOG
    assert out.renames == {} and out.rescored == ()


def test_refresh_rescores_reorders_and_swaps_ids_in_one_pass(make_project) -> None:
    catalog = _catalog()
    catalog["items"][2].update(severity=5, impact="silent_wrong_output")
    catalog["items"][0]["summary"] = "Unblocks TODO-002; TODO-003 waits on a decision."
    out = refresh_items(catalog)
    items = _by_id(out.catalog)
    assert out.renames == {"TODO-002": "TODO-003", "TODO-003": "TODO-002"}
    assert out.rescored == ("TODO-002",)
    assert items["TODO-002"]["title"] == "Choose a cache format"
    assert items["TODO-001"]["unblocks"] == ["TODO-003"]
    assert items["TODO-001"]["summary"] == "Unblocks TODO-003; TODO-002 waits on a decision."
    assert out.catalog["trackers"][0]["child_todo_ids"] == ["TODO-003"]
    assert out.catalog["close_candidates"][0]["related_todo_ids"] == ["TODO-003"]
    _assert_clean(make_project, out.catalog)
