"""TODO catalog rules T1-T10, red and green per rule, on copies of ``TodoCatalog.min.json``. The T6 and
legacy-refusal cases run on ``TodoCatalog.legacy.json`` (rank-tied TODO-001 to TODO-003)."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import (CATALOG_REL, ID1, ID2, ID3, LEGACY_CATALOG, RESEARCH_REL, SNAP_DIR,  # noqa: E402
                           SNAP_REL, build, config, rule_findings, todo_files)

RULES = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10"]


@pytest.mark.parametrize("rule", RULES)
def test_in_sync_project_is_clean(make_project, rule: str) -> None:
    assert rule_findings(build(make_project), rule) == []


def _items(files):
    return files[CATALOG_REL]["items"]


def test_t1_schema_error_names_the_item(make_project) -> None:
    files = todo_files()
    _items(files)[1]["status"] = "DONE"
    [f] = rule_findings(build(make_project, files), "T1")
    assert (f.severity, f.file, f.subject) == ("error", CATALOG_REL, ID2)
    assert f.message.startswith("items/1/status:")


def test_t1_caps_the_listing(make_project) -> None:
    files = todo_files()
    _items(files).extend({**_items(files)[0], "notes": "x"} for _ in range(25))
    findings = rule_findings(build(make_project, files), "T1")
    assert len(findings) == 21
    assert "more finding(s)" in findings[-1].message


def test_t1_prefers_the_project_schema(make_project) -> None:
    files = todo_files()
    files["schemas/Todo.schema.json"] = {"$schema": "http://json-schema.org/draft-07/schema#",
                                         "type": "object", "required": ["owner"]}
    cfg = config()
    cfg["todo"]["catalog_schema"] = "../../../schemas/Todo.schema.json"
    [f] = rule_findings(build(make_project, files, cfg), "T1")
    assert "owner" in f.message


def test_t1_unparseable_catalog_skips_the_other_t_rules(make_project) -> None:
    from harness_lib.todo_sync import check
    files = todo_files()
    files[CATALOG_REL] = "{nope"
    report = check(build(make_project, files), rules=RULES)
    assert [(f.rule, f.file) for f in report.findings] == [("T1", CATALOG_REL)]
    skipped = dict(report.rules_skipped)
    assert all(skipped[r] == "catalog unreadable" for r in RULES[1:])


def test_t1_leaves_legacy_ids_to_t6(make_project) -> None:
    files = todo_files()
    files[CATALOG_REL] = copy.deepcopy(LEGACY_CATALOG)
    assert rule_findings(build(make_project, files), "T1") == []
    _items(files)[1]["status"] = "DONE"
    [f] = rule_findings(build(make_project, files), "T1")
    assert f.message.startswith("items/1/status:")


def test_t2_edited_top_row_warns(make_project) -> None:
    files = todo_files()
    _items(files)[0]["title"] = "Parser drops the first row"
    [f] = rule_findings(build(make_project, files), "T2")
    assert (f.severity, f.file, f.line) == ("warn", SNAP_REL, 1)


def test_t2_ignores_fields_outside_the_rows(make_project) -> None:
    files = todo_files()
    _items(files)[0]["summary"] = "Reworded summary."
    assert rule_findings(build(make_project, files), "T2") == []


def test_t2_snapshot_without_header(make_project) -> None:
    files = todo_files()
    files[SNAP_REL] = "# Repo TODO Snapshot: Top 10\n"
    [f] = rule_findings(build(make_project, files), "T2")
    assert f.message == "snapshot not produced by render (no header)"


def test_t2_newest_snapshot_wins(make_project) -> None:
    files = todo_files()
    files[f"{SNAP_DIR}/TODO_Snapshot_2026_1020.md"] = "no header\n"
    files[f"{SNAP_DIR}/TODO_Snapshot_2026_1018.md"] = files[SNAP_REL]
    [f] = rule_findings(build(make_project, files), "T2")
    assert f.file == f"{SNAP_DIR}/TODO_Snapshot_2026_1020.md"


def test_t2_no_snapshot(make_project) -> None:
    files = todo_files()
    del files[SNAP_REL]
    [f] = rule_findings(build(make_project, files), "T2")
    assert (f.severity, f.file) == ("warn", SNAP_DIR)


def test_t3_unknown_entry_and_missing_source(make_project) -> None:
    files = todo_files()
    _items(files)[1]["catalog_entry_ids"] = ["alpha-loader", "ghost"]
    _items(files)[2]["sources"][0]["ref"] = "docs/RESEARCH/Missing"
    findings = rule_findings(build(make_project, files), "T3")
    assert [(f.subject, "ghost" in f.message) for f in findings] == [(ID2, True), (ID3, False)]


def test_t4_unreferenced_non_terminal_entry(make_project) -> None:
    files = todo_files()
    _items(files)[1]["catalog_entry_ids"] = []
    [f] = rule_findings(build(make_project, files), "T4")
    assert (f.severity, f.file, f.subject) == ("warn", RESEARCH_REL, "alpha-loader")


def test_t5_item_on_terminal_entries_only(make_project) -> None:
    files = todo_files()
    _items(files)[2]["catalog_entry_ids"] = ["beta-cache"]
    [f] = rule_findings(build(make_project, files), "T5")
    assert (f.severity, f.subject) == ("error", ID3)


def _rename(catalog, old: str, new: str) -> None:
    """Rename one id everywhere it is listed (item, links, trackers, close candidates)."""
    text = json.dumps(catalog).replace(f'"{old}"', f'"{new}"')
    catalog.clear()
    catalog.update(json.loads(text))


def test_t6_accepts_ids_that_do_not_follow_rank(make_project) -> None:
    files = todo_files()
    _rename(files[CATALOG_REL], ID1, "todo-zz9z")
    _rename(files[CATALOG_REL], ID3, "todo-2a2a")
    assert [i["id"] for i in _items(files)] == ["todo-zz9z", ID2, "todo-2a2a"]
    assert rule_findings(build(make_project, files), "T6") == []


def test_t6_flags_duplicate_and_retired_ids(make_project) -> None:
    files = todo_files()
    _items(files)[1]["id"] = ID1
    files[CATALOG_REL]["retired_ids"] = [ID3]
    messages = [f.message for f in rule_findings(build(make_project, files), "T6")]
    assert f"id {ID1} appears 2 times" in messages
    assert f"id {ID3} is in retired_ids" in messages
    assert not any("does not match rank" in m for m in messages)


def test_t6_still_checks_ranks_run_1_to_n(make_project) -> None:
    files = todo_files()
    _items(files)[2]["rank"] = 7
    [f] = rule_findings(build(make_project, files), "T6")
    assert (f.message, f.subject) == ("rank 7 at position 3", ID3)


def test_t6_reports_a_legacy_catalog_once(make_project) -> None:
    files = todo_files()
    files[CATALOG_REL] = copy.deepcopy(LEGACY_CATALOG)
    [f] = rule_findings(build(make_project, files), "T6")
    assert (f.severity, f.file) == ("error", CATALOG_REL)
    assert "TODO-NNN" in f.message and "migrate-ids" in f.message
    assert "migrate-ids --dry-run" in f.fix


def test_t6_keeps_the_duplicate_check_on_a_legacy_catalog(make_project) -> None:
    files = todo_files()
    files[CATALOG_REL] = copy.deepcopy(LEGACY_CATALOG)
    _items(files)[2]["id"] = "TODO-002"
    messages = [f.message for f in rule_findings(build(make_project, files), "T6")]
    assert len(messages) == 2
    assert any("migrate-ids" in m for m in messages)
    assert "id TODO-002 appears 2 times" in messages


def test_t6_checks_split_ids(make_project) -> None:
    files = todo_files()
    files[CATALOG_REL]["retired_ids"] = ["todo-m3x9"]
    files[CATALOG_REL]["split_ids"] = {"todo-m3x9": [ID2, "todo-2a2a"], "todo-k7qf": [ID1, ID3]}
    messages = [f.message for f in rule_findings(build(make_project, files), "T6")]
    assert sorted(messages) == ["split id todo-k7qf is not in retired_ids",
                                "split id todo-m3x9 names part todo-2a2a, neither an item nor retired"]
    files[CATALOG_REL]["retired_ids"] = ["todo-m3x9", "todo-2a2a", "todo-k7qf"]
    assert rule_findings(build(make_project, files), "T6") == []


def test_t7_one_sided_dependency(make_project) -> None:
    files = todo_files()
    _items(files)[1]["depends_on"] = [ID1, "todo-9zzz"]
    _items(files)[0]["unblocks"] = []
    findings = rule_findings(build(make_project, files), "T7")
    assert sorted(f.subject for f in findings) == [ID2, ID2]


def test_t8_tracker_membership(make_project) -> None:
    files = todo_files()
    _items(files)[2]["tracker"] = 999
    files[CATALOG_REL]["trackers"][0]["child_todo_ids"] = [ID2, ID3]
    messages = [f.message for f in rule_findings(build(make_project, files), "T8")]
    assert any("#999 is not in trackers" in m for m in messages)
    assert any("child_todo_ids" in m for m in messages)


@pytest.mark.parametrize("key,value", [("items", 4), ("by_status", {"OPEN": 3}), ("by_loe", {"S": 3})])
def test_t9_counts_drift(make_project, key: str, value) -> None:
    files = todo_files()
    files[CATALOG_REL]["counts"][key] = value
    [f] = rule_findings(build(make_project, files), "T9")
    assert f.subject == f"counts.{key}"


def test_t9_zero_tallies_compare_equal(make_project) -> None:
    files = todo_files()
    files[CATALOG_REL]["counts"]["by_status"]["BLOCKED"] = 0
    assert rule_findings(build(make_project, files), "T9") == []


def test_t10_severity_edit_breaks_score_and_rank(make_project) -> None:
    files = todo_files()
    _items(files)[2]["severity"] = 5
    findings = rule_findings(build(make_project, files), "T10")
    by_subject = {}
    for f in findings:
        by_subject.setdefault(f.subject, []).append(f.message)
    assert any("score 0.3464 != 0.866" in m for m in by_subject[ID3])
    assert any("recomputed order puts it at 2" in m for m in by_subject[ID3])


def test_t10_component_drift(make_project) -> None:
    files = todo_files()
    _items(files)[0]["priority"]["components"]["cost"] = 2.5
    [f] = rule_findings(build(make_project, files), "T10")
    assert "cost 2.5 != 2.0" in f.message


def test_t10_missing_ranking_tables(make_project) -> None:
    files = todo_files()
    del files[CATALOG_REL]["ranking_method"]["loe_points"]
    [f] = rule_findings(build(make_project, files), "T10")
    assert "loe_points" in f.message


def test_malformed_item_is_a_finding_not_a_traceback(make_project) -> None:
    from harness_lib.todo_sync import check
    files = todo_files()
    _items(files)[0]["severity"] = "high"
    report = check(build(make_project, files), rules=["T10"])
    assert report.findings and all(f.rule == "T10" for f in report.findings)
    json.dumps(report.to_dict())
