"""Retiring finished TODO items: removal, re-ranking, the retired-id record and counts, on copies of
``TodoCatalog.min.json`` (ID1 unblocks ID2; ID2 sits under tracker #101 and names #102). No id other than
the retired ones changes, and nothing outside the catalog is rewritten. The legacy-refusal test runs on
``TodoCatalog.legacy.json`` (rank-tied TODO-001 to TODO-003)."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import (CATALOG_REL, ID1, ID2, ID3, LEGACY_CATALOG, MIN_CATALOG, RESEARCH_REL,  # noqa: E402
                           STUB_REL, build, rule_findings, stub_text, todo_files)
from harness_lib.todo_sync import TodoSyncError, retire  # noqa: E402
from harness_lib.todo_sync.retire import (apply_retirement, history_paths, other_references,  # noqa: E402
                                          retire_items, summary_lines)
from harness_lib.todo_sync.sources import posix  # noqa: E402

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


def test_unknown_id_is_refused() -> None:
    with pytest.raises(TodoSyncError, match="todo-9zzz"):
        retire_items(_catalog(), ["todo-9zzz"])


def test_input_catalog_is_not_mutated() -> None:
    catalog = _catalog()
    retire_items(catalog, [ID1])
    assert catalog == MIN_CATALOG


def test_retire_records_the_id_and_keeps_every_other_id(make_project) -> None:
    out = retire_items(_catalog(), [ID1])
    assert _ids(out.catalog) == [ID2, ID3]
    assert out.catalog["retired_ids"] == [ID1]
    assert [i["id"] for i in out.retired] == [ID1]
    _assert_clean(make_project, out.catalog)


def test_retire_reranks_without_renaming(make_project) -> None:
    catalog = _catalog()
    catalog["items"][2]["summary"] = f"Waits on the decision noted in {ID3} itself."
    out = retire_items(catalog, [ID1, ID1.upper()])
    items = out.catalog["items"]
    assert [(i["id"], i["rank"]) for i in items] == [(ID2, 1), (ID3, 2)]
    assert items[0]["depends_on"] == []
    assert items[1]["summary"] == f"Waits on the decision noted in {ID3} itself."
    assert out.catalog["trackers"][0]["child_todo_ids"] == [ID2]
    assert out.catalog["close_candidates"][0]["related_todo_ids"] == [ID2]
    assert not hasattr(out, "renames")
    _assert_clean(make_project, out.catalog)


def test_retired_ids_accumulate() -> None:
    catalog = _catalog()
    catalog["retired_ids"] = ["todo-2a2a"]
    out = retire_items(catalog, [ID3, ID1])
    assert out.catalog["retired_ids"] == ["todo-2a2a", ID1, ID3]
    assert _ids(out.catalog) == [ID2]


def test_losing_the_only_unblocked_item_drops_the_bonus(make_project) -> None:
    before = MIN_CATALOG["items"][0]["priority"]
    assert before["components"]["unblock_bonus"] > 0
    out = retire_items(_catalog(), [ID2])
    first = next(i for i in out.catalog["items"] if i["id"] == ID1)
    assert first["unblocks"] == []
    assert first["priority"]["components"]["unblock_bonus"] == 0
    assert first["priority"]["score"] < before["score"]
    _assert_clean(make_project, out.catalog)


def test_a_retired_child_leaves_trackers_and_close_candidates(make_project) -> None:
    out = retire_items(_catalog(), [ID2])
    assert _ids(out.catalog) == [ID1, ID3]
    assert out.catalog["trackers"][0]["child_todo_ids"] == []
    assert out.catalog["close_candidates"][0]["related_todo_ids"] == []
    _assert_clean(make_project, out.catalog)


def test_counts_follow_the_items_and_keep_zero_keys() -> None:
    out = retire_items(_catalog(), [ID1])
    counts = out.catalog["counts"]
    assert counts["items"] == 2
    assert counts["by_status"] == {"NEEDS_DECISION": 1, "OPEN": 0, "PARTIAL": 1}
    assert counts["by_loe"]["XL"] == 0
    assert list(counts["by_loe"]) == list(MIN_CATALOG["counts"]["by_loe"])
    assert counts["sources_absorbed"]["gh_issue"] == MIN_CATALOG["counts"]["sources_absorbed"]["gh_issue"] - 1


def test_a_retired_id_left_in_prose_is_reported_not_rewritten() -> None:
    catalog = _catalog()
    catalog["items"][1]["summary"] = f"Picks up after {ID1} lands."
    catalog["items"][2]["summary"] = f"Also waits on {ID1.upper()}."
    out = retire_items(catalog, [ID1])
    assert out.catalog["items"][0]["summary"] == f"Picks up after {ID1} lands."
    assert out.dangling == (f"items/{ID2}/summary names retired {ID1}",
                            f"items/{ID3}/summary names retired {ID1}")


def test_dangling_skips_the_id_records() -> None:
    catalog = _catalog()
    catalog["retired_ids"] = ["todo-2a2a"]
    catalog["legacy_ids"] = {"migrated": "2026-11-09", "map": {"TODO-001": ID1, "TODO-017": "todo-2a2a"}}
    catalog["split_ids"] = {"todo-2a2a": [ID1, ID3]}
    catalog["items"][1]["summary"] = f"Picks up after {ID1} lands."
    out = retire_items(catalog, [ID1])
    assert out.dangling == (f"items/{ID2}/summary names retired {ID1}",)
    assert out.catalog["legacy_ids"] == catalog["legacy_ids"]
    assert out.catalog["split_ids"] == catalog["split_ids"]
    assert out.catalog["retired_ids"] == ["todo-2a2a", ID1]


def test_report_names_open_issues_and_touched_trackers() -> None:
    out = retire_items(_catalog(), [ID1, ID2])
    assert out.issues_to_close == (11,)
    assert out.trackers_touched == (101,)


def test_an_issue_already_listed_as_close_candidate_is_not_repeated() -> None:
    catalog = _catalog()
    catalog["items"][0]["gh_issues"] = [102]
    out = retire_items(catalog, [ID1])
    assert out.issues_to_close == ()


def test_retire_names_a_retired_or_old_id() -> None:
    catalog = _catalog()
    catalog["retired_ids"] = ["todo-2a2a"]
    with pytest.raises(TodoSyncError, match="todo-2a2a was retired"):
        retire_items(catalog, ["todo-2a2a"])
    with pytest.raises(TodoSyncError, match="TODO-007"):
        retire_items(catalog, ["7"])


def test_retire_refuses_a_legacy_catalog() -> None:
    with pytest.raises(TodoSyncError, match="migrate-ids"):
        retire_items(copy.deepcopy(LEGACY_CATALOG), ["TODO-001"])


def test_companion_mentions_are_listed_not_rewritten(make_project) -> None:
    files = todo_files()
    files[STUB_REL] = stub_text() + f"\nTracked as {ID1}.\n"
    files[RESEARCH_REL] = {"description": f"Loader work is {ID1}.", **files[RESEARCH_REL]}
    cfg = build(make_project, files)
    stub_before = (cfg.project_root / STUB_REL).read_bytes()
    research_before = (cfg.project_root / RESEARCH_REL).read_bytes()
    result = apply_retirement(cfg, [ID1])
    assert (cfg.project_root / STUB_REL).read_bytes() == stub_before
    assert (cfg.project_root / RESEARCH_REL).read_bytes() == research_before
    assert f"{STUB_REL}:12 names retired {ID1}" in result.dangling
    assert any(d.startswith(f"{RESEARCH_REL}:") and d.endswith(f"names retired {ID1}")
               for d in result.dangling)
    written = json.loads((cfg.project_root / CATALOG_REL).read_text(encoding="utf-8"))
    assert written["retired_ids"] == [ID1] and _ids(written) == [ID2, ID3]
    assert not hasattr(result, "rewritten")


def test_other_references_name_only_the_retired_ids(make_project) -> None:
    files = {**todo_files(), "docs/notes.md": f"See {ID1}.\nAlso {ID3}.\nUpper {ID1.upper()}.\n"}
    cfg = build(make_project, files)
    for folder in (cfg.artifacts.plans, cfg.artifacts.reviews, cfg.artifacts.commit_messages):
        record = cfg.project_root / folder / "0001_Old.md"
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(f"Executed under {ID1}.\n", encoding="utf-8")
    refs = other_references(cfg, [ID1])
    assert refs == (f"docs/notes.md:1:See {ID1}.", f"docs/notes.md:3:Upper {ID1.upper()}.")
    assert other_references(cfg, []) == ()


def test_history_paths_include_commit_messages(make_project) -> None:
    cfg = build(make_project)
    paths = history_paths(cfg)
    for folder in (cfg.artifacts.plans, cfg.artifacts.reviews, cfg.artifacts.commit_messages,
                   cfg.todo.snapshots.dir, cfg.artifacts.summaries, cfg.artifacts.scratch,
                   *cfg.artifacts.planning_prefixes):
        assert posix(folder).rstrip("/") in paths


def test_a_failed_reference_scan_is_reported(make_project, monkeypatch) -> None:
    cfg = build(make_project)

    def broken(*args, **kwargs):
        raise OSError("git went away")

    monkeypatch.setattr(retire.subprocess, "run", broken)
    with pytest.raises(TodoSyncError, match="git grep failed: git went away"):
        other_references(cfg, [ID1])
    result = apply_retirement(cfg, [ID1])
    assert result.references == ()
    assert result.scan_error == "git grep failed: git went away"
    assert "reference scan failed: git grep failed: git went away" in summary_lines(result, False)
    written = json.loads((cfg.project_root / CATALOG_REL).read_text(encoding="utf-8"))
    assert written["retired_ids"] == [ID1]
