"""Splitting one TODO item into parts and refreshing the ranking, on copies of ``TodoCatalog.min.json``
(ID1 unblocks ID2; ID2 sits under tracker #101 and names close candidate #102). Parts get new ids, the
split item's id is retired, and no other id ever changes; only ranks move. The legacy-refusal tests run
on ``TodoCatalog.legacy.json`` (rank-tied TODO-001 to TODO-003)."""
from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import (CATALOG_REL, ID1, ID2, ID3, LEGACY_CATALOG, MIN_CATALOG,  # noqa: E402
                           Scripted, build, rule_findings, todo_files)
from harness_lib.todo_sync import TodoSyncError  # noqa: E402
from harness_lib.todo_sync.ids import is_id  # noqa: E402
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
    """ID2 split in two: the XS part outranks the inherited M part."""
    return [
        {"title": "Split the loader reads", "loe": {"size": "XS", "reasoning": "One function."}},
        {"title": "Split the loader writes"},
    ]


def test_split_gives_parts_new_ids_and_retires_the_original(make_project) -> None:
    out = split_item(_catalog(), ID2.upper(), _loader_parts(), rng=random.Random(7))
    reads, writes = out.parts
    assert out.split == ID2
    assert is_id(reads) and is_id(writes) and not {reads, writes} & {ID1, ID2, ID3}
    ranked = [(i["id"], i["rank"]) for i in out.catalog["items"]]
    assert ranked == [(ID1, 1), (reads, 2), (writes, 3), (ID3, 4)]
    assert out.catalog["retired_ids"] == [ID2]
    assert out.catalog["split_ids"] == {ID2: [reads, writes]}
    items = _by_id(out.catalog)
    assert items[reads]["title"] == "Split the loader reads"
    assert items[writes]["title"] == "Split the loader writes"
    assert items[reads]["priority"]["score"] == 1.4606
    assert out.catalog["counts"]["items"] == 4
    assert not hasattr(out, "renames")
    _assert_clean(make_project, out.catalog)


def test_split_inherits_links_tracker_and_close_candidates(make_project) -> None:
    out = split_item(_catalog(), ID2, _loader_parts())
    items = _by_id(out.catalog)
    parts = sorted(out.parts)
    assert items[ID1]["unblocks"] == parts
    assert items[out.parts[0]]["depends_on"] == [ID1] == items[out.parts[1]]["depends_on"]
    assert out.catalog["trackers"][0]["child_todo_ids"] == parts
    assert out.catalog["close_candidates"][0]["related_todo_ids"] == parts
    _assert_clean(make_project, out.catalog)


def test_split_prose_naming_the_original_is_flagged_not_rewritten(make_project) -> None:
    catalog = _catalog()
    catalog["items"][2]["summary"] = f"After {ID1} lands; see {ID2} too."
    parts = [{"title": "Parser drops the last row on CRLF input", "severity": 3},
             {"title": "Parser drops the last row on LF input"}]
    out = split_item(catalog, ID1, parts)
    crlf, lf = out.parts
    items = _by_id(out.catalog)
    assert items[ID3]["summary"] == f"After {ID1} lands; see {ID2} too."
    assert out.flagged == (f"items/{ID3}/summary names split {ID1} (parts {crlf}, {lf})",)
    assert items[ID2]["depends_on"] == sorted(out.parts)
    _assert_clean(make_project, out.catalog)


def test_split_flags_skip_the_id_records() -> None:
    catalog = _catalog()
    catalog["legacy_ids"] = {"migrated": "2026-11-09", "map": {"TODO-002": ID2}}
    catalog["items"][2]["summary"] = f"See {ID2.upper()} first."
    out = split_item(catalog, ID2, _loader_parts())
    reads, writes = out.parts
    assert out.flagged == (f"items/{ID3}/summary names split {ID2} (parts {reads}, {writes})",)
    assert out.catalog["legacy_ids"] == catalog["legacy_ids"]


def test_split_never_draws_a_live_retired_or_original_id() -> None:
    catalog = _catalog()
    catalog["retired_ids"] = ["todo-2a2a"]
    rng = Scripted("p4rs" + "sp7t" + "2a2a" + "k7qf" + "m3x9")
    out = split_item(catalog, ID2, _loader_parts(), rng=rng)
    assert out.parts == ("todo-k7qf", "todo-m3x9")
    assert out.catalog["retired_ids"] == ["todo-2a2a", ID2]


def test_split_does_not_mutate_its_input() -> None:
    catalog = _catalog()
    split_item(catalog, ID2, _loader_parts())
    assert catalog == MIN_CATALOG


@pytest.mark.parametrize(("parts", "message"), [
    ([{"title": "Only one"}], "at least two parts"),
    ([{"title": "A", "id": "todo-9zzz"}, {"title": "B"}], "sets id"),
    ([{"title": "A", "priority": {}}, {"title": "B"}], "sets priority"),
    ([{"summary": "no title"}, {"title": "B"}], "needs a title"),
    ([{"title": "Same"}, {"title": "Same"}], "share the title"),
    ([{"title": "A", "unblocks": ["todo-9zzz"]}, {"title": "B"}], "todo-9zzz"),
    ([{"title": "A", "unblocks": [ID2]}, {"title": "B"}], "names the item being split"),
    (["not an object", {"title": "B"}], "not an object"),
])
def test_split_refuses_a_bad_spec(parts, message: str) -> None:
    with pytest.raises(TodoSyncError, match=message):
        split_item(_catalog(), ID2, parts)


def test_split_unknown_id_is_refused() -> None:
    with pytest.raises(TodoSyncError, match="todo-9zzz"):
        split_item(_catalog(), "9zzz", _loader_parts())


def test_split_refuses_a_legacy_catalog() -> None:
    with pytest.raises(TodoSyncError, match="migrate-ids"):
        split_item(copy.deepcopy(LEGACY_CATALOG), "TODO-002", _loader_parts())


def test_refresh_of_a_ranked_catalog_changes_nothing() -> None:
    out = refresh_items(_catalog())
    assert out.catalog == MIN_CATALOG
    assert out.rescored == () and out.reranked == ()


def test_refresh_reranks_without_renaming(make_project) -> None:
    catalog = _catalog()
    catalog["items"][2].update(severity=5, impact="silent_wrong_output")
    catalog["items"][0]["summary"] = f"Unblocks {ID2}; {ID3} waits on a decision."
    out = refresh_items(catalog)
    assert out.rescored == (ID3,)
    assert out.reranked == ((ID3, 3, 2), (ID2, 2, 3))
    assert [(i["id"], i["rank"]) for i in out.catalog["items"]] == [(ID1, 1), (ID3, 2), (ID2, 3)]
    items = _by_id(out.catalog)
    assert items[ID3]["title"] == "Choose a cache format"
    assert items[ID1]["unblocks"] == [ID2]
    assert items[ID1]["summary"] == f"Unblocks {ID2}; {ID3} waits on a decision."
    assert out.catalog["trackers"][0]["child_todo_ids"] == [ID2]
    assert out.catalog["close_candidates"][0]["related_todo_ids"] == [ID2]
    _assert_clean(make_project, out.catalog)
