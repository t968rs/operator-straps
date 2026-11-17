"""Field updates of existing TODO items: ``updates.apply_updates`` validates and applies an update spec,
``inbox.put_updates`` queues one inbox file per update without touching the catalog, and ``inbox.drain``
applies queued updates beside queued adds, oldest first, in one catalog write.

An update sets only the fields an ``add`` spec may carry (never ``issue`` or ``url``), names a live item, and
re-ranks the catalog. Two queued updates of one field of one item: the later wins and the drain names it.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, ID1, ID2, ID3, MIN_CATALOG, build, todo_files  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, inbox, updates  # noqa: E402
from harness_lib.todo_sync.reshape import ADD_OPTIONAL, ADD_REQUIRED  # noqa: E402

WALK_ROOTS = ()
DAY = dt.date(2026, 11, 17)
RISE = {"severity": 5, "impact": "silent_wrong_output"}
#: Queued file names as ``put`` draws them; FIRST sorts before SECOND.
FIRST = "20261117T000001000000Z-00-aaaaaa.json"
SECOND = "20261117T000002000000Z-00-bbbbbb.json"


def _update(item_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """A queued update file's body: one update."""
    return {"updates": [{"id": item_id, "fields": fields}]}


def _catalog(cfg=None) -> Dict[str, Any]:
    if cfg is None:
        return copy.deepcopy(MIN_CATALOG)
    return json.loads(cfg.path(CATALOG_REL).read_text(encoding="utf-8"))


def _item(catalog: Dict[str, Any], item_id: str) -> Dict[str, Any]:
    return next(i for i in catalog["items"] if i["id"] == item_id)


def _spec(tmp_path: Path, entries: List[Dict[str, Any]], name: str = "update.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps({"updates": entries}), encoding="utf-8")
    return path


def _queue(cfg, name: str, body: Dict[str, Any]) -> Path:
    folder = inbox.inbox_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _added(issue: int) -> Dict[str, Any]:
    return {"items": [{"issue": issue, "url": f"https://github.com/example/widgets/issues/{issue}",
                       "title": f"New problem {issue}", "kind": "bug", "summary": "The parser skips a row.",
                       "proposed_change": "Read every row.", "impact": "silent_wrong_output", "severity": 5,
                       "why_ranked": "Computed from ranking_method.",
                       "blast_radius": {"level": "S", "reasoning": "One module.", "consumers": []},
                       "loe": {"size": "S", "reasoning": "Small."}}]}


def _names(cfg) -> List[str]:
    return sorted(p.name for p in inbox.inbox_dir(cfg).iterdir())


def test_update_fields_are_the_add_fields_without_the_issue() -> None:
    assert set(updates.UPDATE_FIELDS) == set(ADD_REQUIRED + ADD_OPTIONAL) - {"issue", "url"}


def test_apply_updates_sets_the_fields_and_reranks() -> None:
    out = updates.apply_updates(_catalog(), [{"id": ID3, "fields": RISE}])
    item = _item(out.catalog, ID3)
    assert (item["severity"], item["impact"], item["rank"]) == (5, "silent_wrong_output", 2)
    assert _item(out.catalog, ID2)["rank"] == 3
    assert out.updated == ((ID3, ("severity", "impact")),)
    assert _item(_catalog(), ID3)["rank"] == 3, "the input catalog is left as it was"


def test_an_update_leaves_every_other_field() -> None:
    before = _item(_catalog(), ID2)
    out = updates.apply_updates(_catalog(), [{"id": ID2, "fields": {"summary": "Narrowed to one file."}}])
    assert _item(out.catalog, ID2) == {**before, "summary": "Narrowed to one file."}


def test_an_id_is_read_in_any_case_and_without_its_prefix() -> None:
    out = updates.apply_updates(_catalog(), [{"id": ID3.upper()[len("todo-"):], "fields": RISE}])
    assert out.updated == ((ID3, ("severity", "impact")),)


@pytest.mark.parametrize("field", ["id", "rank", "priority", "depends_on", "unblocks", "sources", "gh_issues",
                                   "tracker", "catalog_entry_ids", "issue", "url"])
def test_a_field_outside_the_list_is_refused(field: str) -> None:
    with pytest.raises(TodoSyncError, match=f"update 1 sets {field}"):
        updates.apply_updates(_catalog(), [{"id": ID1, "fields": {field: []}}])


def test_a_retired_or_split_id_is_refused() -> None:
    catalog = {**_catalog(), "retired_ids": ["todo-r3t9", "todo-s9p2"], "split_ids": {"todo-s9p2": [ID3]}}
    with pytest.raises(TodoSyncError, match="todo-r3t9 was retired"):
        updates.apply_updates(catalog, [{"id": "todo-r3t9", "fields": {"summary": "x"}}])
    with pytest.raises(TodoSyncError, match="todo-s9p2 was split into"):
        updates.apply_updates(catalog, [{"id": "todo-s9p2", "fields": {"summary": "x"}}])


@pytest.mark.parametrize("entry, needle", [
    ({"id": ID1, "fields": {"severity": 9}}, "severity must be"),
    ({"id": ID1, "fields": {"kind": "chore"}}, "update 1"),
    ({"id": ID1, "fields": {}}, "update 1 sets no field"),
    ({"id": ID1}, "update 1 sets no field"),
    ({"fields": {"summary": "x"}}, "update 1 names no id"),
    ("todo-p4rs", "update 1 is not an object"),
], ids=["severity", "kind", "empty-fields", "no-fields", "no-id", "not-object"])
def test_a_bad_update_is_refused(entry: Any, needle: str) -> None:
    with pytest.raises(TodoSyncError, match=needle):
        updates.apply_updates(_catalog(), [entry])


def test_one_spec_sets_a_field_once() -> None:
    entries = [{"id": ID1, "fields": {"summary": "a"}}, {"id": ID1.upper(), "fields": {"summary": "b"}}]
    with pytest.raises(TodoSyncError, match=f"update 2 sets {ID1} summary again"):
        updates.apply_updates(_catalog(), entries)


def test_an_empty_spec_is_refused() -> None:
    with pytest.raises(TodoSyncError, match="at least one update"):
        updates.apply_updates(_catalog(), [])


def test_put_updates_queues_one_file_per_update_and_leaves_the_catalog(make_project, tmp_path: Path) -> None:
    cfg = build(make_project)
    before = cfg.path(CATALOG_REL).read_bytes()
    entries = [{"id": ID3, "fields": RISE}, {"id": ID2, "fields": {"summary": "Narrowed."}}]
    result = inbox.put_updates(cfg, _spec(tmp_path, entries))
    assert cfg.path(CATALOG_REL).read_bytes() == before
    bodies = [json.loads(p.read_text(encoding="utf-8")) for p in result.paths]
    assert bodies == [{"updates": [entries[0]]}, {"updates": [entries[1]]}]
    assert [p.name for p in result.paths] == [p.name for p in inbox.queued(cfg)]


def test_put_updates_writes_nothing_on_a_refusal(make_project, tmp_path: Path) -> None:
    cfg = build(make_project)
    with pytest.raises(TodoSyncError, match="update 2 sets rank"):
        inbox.put_updates(cfg, _spec(tmp_path, [{"id": ID3, "fields": RISE},
                                                {"id": ID2, "fields": {"rank": 1}}]))
    assert inbox.queued(cfg) == []


def test_drain_applies_adds_and_updates_in_one_write(make_project) -> None:
    cfg = build(make_project)
    _queue(cfg, FIRST, _added(9))
    _queue(cfg, SECOND, _update(ID3, RISE))
    result = inbox.drain(cfg, today=DAY)
    assert [issue for _, issue in result.added] == [9]
    assert result.updated == ((ID3, ("severity", "impact")),)
    assert result.overwritten == () and result.rejected == ()
    assert _item(_catalog(cfg), ID3)["severity"] == 5
    assert inbox.queued(cfg) == [] and _names(cfg) == []
    assert result.drift == 0


def test_a_later_update_of_one_field_wins_and_is_named(make_project) -> None:
    cfg = build(make_project)
    _queue(cfg, FIRST, _update(ID2, {"summary": "a"}))
    _queue(cfg, SECOND, _update(ID2, {"summary": "b"}))
    result = inbox.drain(cfg, today=DAY)
    assert _item(_catalog(cfg), ID2)["summary"] == "b"
    assert result.updated == ((ID2, ("summary",)),), "one entry per item, fields merged in first-set order"
    assert result.overwritten == ((ID2, "summary"),)


def test_updates_of_one_item_from_two_files_merge_their_fields(make_project) -> None:
    cfg = build(make_project)
    _queue(cfg, FIRST, _update(ID3, {"summary": "a"}))
    _queue(cfg, SECOND, _update(ID3, RISE))
    result = inbox.drain(cfg, today=DAY)
    assert result.updated == ((ID3, ("summary", "severity", "impact")),)
    assert result.overwritten == ()


def test_drain_refuses_an_update_of_a_retired_id(make_project) -> None:
    files = todo_files()
    files[CATALOG_REL]["retired_ids"] = ["todo-r3t9"]
    cfg = build(make_project, files)
    before = cfg.path(CATALOG_REL).read_bytes()
    _queue(cfg, FIRST, _update("todo-r3t9", RISE))
    result = inbox.drain(cfg, today=DAY)
    [(name, reason)] = result.rejected
    assert name == FIRST and "was retired" in reason
    assert result.updated == ()
    assert cfg.path(CATALOG_REL).read_bytes() == before


def test_drain_refuses_an_update_that_sets_a_computed_field(make_project) -> None:
    cfg = build(make_project)
    _queue(cfg, FIRST, _update(ID3, {"rank": 1}))
    _queue(cfg, SECOND, _update(ID2, {"summary": "b"}))
    result = inbox.drain(cfg, today=DAY)
    [(name, reason)] = result.rejected
    assert name == FIRST and "sets rank" in reason
    assert result.updated == ((ID2, ("summary",)),)


def test_drain_lines_name_the_updates_and_the_overwrites() -> None:
    both = inbox.DrainResult(added=(("todo-k7qf", 9),), updated=((ID3, ("summary", "severity")),),
                             overwritten=((ID3, "summary"),), drift=0)
    assert inbox.drain_lines(both) == [
        f"inbox: added 1 item(s): todo-k7qf (#9); updated 1 item(s): {ID3} (summary, severity); "
        f"overwrote {ID3} summary; check drift=0"]
    alone = inbox.DrainResult(updated=((ID3, ("summary",)),), rejected=(("x.json", "no"),), drift=1)
    assert inbox.drain_lines(alone) == [
        f"inbox: updated 1 item(s): {ID3} (summary); rejected 1 (x.json); check drift=1"]


def test_drain_lines_of_adds_alone_are_unchanged() -> None:
    result = inbox.DrainResult(added=(("todo-k7qf", None),), drift=0)
    assert inbox.drain_lines(result) == ["inbox: added 1 item(s): todo-k7qf (note); check drift=0"]
