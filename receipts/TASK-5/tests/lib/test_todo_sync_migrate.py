"""The one-time switch from rank-tied ``TODO-NNN`` ids to stable ``todo-xxxx`` ids, on copies of
``TodoCatalog.legacy.json`` (TODO-001 unblocks TODO-002; TODO-002 sits under tracker #101 and names close
candidate #102). Live files are rewritten through the map; history records are left as written. A rerun on
a migrated catalog finishes the job through the stored map."""
from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path
from typing import Dict

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import (CATALOG_REL, LEGACY_CATALOG, MIN_CATALOG, RESEARCH_REL,  # noqa: E402
                           STUB_REL, TODO_DIR, build, stub_text, todo_files)
from harness_lib.todo_sync import TodoSyncError, check, migrate, retire  # noqa: E402
from harness_lib.todo_sync.ids import is_id  # noqa: E402
from harness_lib.todo_sync.migrate import apply_migration, migrate_catalog, summary_lines  # noqa: E402
from harness_lib.todo_sync.sources import posix  # noqa: E402

DAY = "2026-11-09"
OLD = ["TODO-001", "TODO-002", "TODO-003"]
CATALOG_RULES = ["T1", "T6", "T7", "T8", "T9", "T10"]
SCHEMA_REL = f"{TODO_DIR}/RepoToDo.schema.json"
DRAFT = "https://json-schema.org/draft/2020-12/schema"
LEGACY_SCHEMA = {"$schema": DRAFT, "type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string", "pattern": "^TODO-[0-9]{3,}$"}}}}}}


def _legacy():
    return copy.deepcopy(LEGACY_CATALOG)


def _legacy_files() -> Dict[str, object]:
    files = todo_files()
    files[CATALOG_REL] = _legacy()
    return files


def _read(cfg, rel: str) -> str:
    return (cfg.project_root / rel).read_text(encoding="utf-8")


def _write(cfg, rel: str, text: str) -> Path:
    path = cfg.project_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_migrate_gives_every_item_a_stable_id_and_keeps_the_map() -> None:
    catalog = _legacy()
    out = migrate_catalog(catalog, DAY, rng=random.Random(1))
    assert list(out.mapping) == OLD
    new = list(out.mapping.values())
    assert all(is_id(i) for i in new) and len(set(new)) == 3
    assert [(i["id"], i["rank"]) for i in out.catalog["items"]] == list(zip(new, [1, 2, 3]))
    assert out.catalog["legacy_ids"] == {"migrated": DAY, "map": out.mapping}
    assert out.catalog["retired_ids"] == []
    assert catalog == LEGACY_CATALOG


def test_migrate_rewrites_links_and_prose_in_one_pass() -> None:
    catalog = _legacy()
    catalog["items"][2]["summary"] = "After TODO-001; see TODO-002 and TODO-003."
    catalog["items"][0]["unblocks"] = ["TODO-002", "TODO-003"]
    catalog["items"][2]["depends_on"] = ["TODO-001"]
    catalog["close_candidates"][0]["related_todo_ids"] = ["TODO-003", "TODO-002"]
    out = migrate_catalog(catalog, DAY)
    m = out.mapping
    items = out.catalog["items"]
    assert items[2]["summary"] == f"After {m['TODO-001']}; see {m['TODO-002']} and {m['TODO-003']}."
    assert items[0]["unblocks"] == sorted([m["TODO-002"], m["TODO-003"]])
    assert items[1]["depends_on"] == [m["TODO-001"]]
    assert out.catalog["trackers"][0]["child_todo_ids"] == [m["TODO-002"]]
    assert out.catalog["close_candidates"][0]["related_todo_ids"] == [m["TODO-003"], m["TODO-002"]]
    assert "TODO-00" not in json.dumps({k: v for k, v in out.catalog.items() if k != "legacy_ids"})


def test_migrate_lists_old_ids_with_no_live_item() -> None:
    catalog = _legacy()
    catalog["items"][0]["summary"] = "Replaces TODO-017."
    catalog["close_candidates"][0]["related_todo_ids"] = ["TODO-002", "TODO-099"]
    out = migrate_catalog(catalog, DAY)
    first = out.mapping["TODO-001"]
    assert out.catalog["items"][0]["summary"] == "Replaces TODO-017."
    assert out.catalog["close_candidates"][0]["related_todo_ids"] == [out.mapping["TODO-002"]]
    assert out.unmapped == (f"items/{first}/summary names TODO-017, no live item",
                            "close_candidates/0/related_todo_ids dropped TODO-099, no live item")


def test_migrate_refuses_a_stable_catalog() -> None:
    with pytest.raises(TodoSyncError, match="nothing to migrate"):
        migrate_catalog(copy.deepcopy(MIN_CATALOG), DAY)


def test_migration_ids_are_reproducible(make_project) -> None:
    first = migrate_catalog(_legacy(), DAY).mapping
    assert migrate_catalog(_legacy(), "2027-01-01").mapping == first
    cfg = build(make_project, _legacy_files())
    dry = apply_migration(cfg, dry_run=True, today=DAY).migration.mapping
    real = apply_migration(cfg, today=DAY).migration.mapping
    assert dry == real == first


def test_migrate_refuses_duplicate_legacy_ids() -> None:
    catalog = _legacy()
    catalog["items"][2]["id"] = "TODO-002"
    with pytest.raises(TodoSyncError, match=r"duplicate legacy id\(s\): TODO-002"):
        migrate_catalog(catalog, DAY)


def test_migrate_refuses_a_key_already_in_the_map() -> None:
    catalog = _legacy()
    catalog["legacy_ids"] = {"migrated": "2026-11-01", "map": {"TODO-002": "todo-k7qf"}}
    refusal = r"TODO-002 is already in legacy_ids \(migrated 2026-11-01\).*restore it from git"
    with pytest.raises(TodoSyncError, match=refusal):
        migrate_catalog(catalog, DAY)


def test_migrate_adds_new_legacy_ids_to_the_stored_map() -> None:
    first = migrate_catalog(_legacy(), DAY)
    catalog = copy.deepcopy(first.catalog)
    catalog["items"][2]["id"] = "TODO-004"
    out = migrate_catalog(catalog, "2026-11-10")
    assert list(out.mapping) == ["TODO-004"] and is_id(out.mapping["TODO-004"])
    assert out.catalog["legacy_ids"] == {"migrated": DAY, "map": {**first.mapping, **out.mapping}}


def test_apply_rewrites_companions_and_live_files(make_project) -> None:
    files = _legacy_files()
    files[STUB_REL] = stub_text() + "\nTracked as TODO-002.\n"
    files[RESEARCH_REL] = {"description": "Loader work is TODO-002.", **files[RESEARCH_REL]}
    cfg = build(make_project, files)
    notes = cfg.project_root / "docs" / "notes.md"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_bytes(b"See TODO-003 and TODO-017.\r\n")
    result = apply_migration(cfg, today=DAY, rng=random.Random(3))
    m = result.migration.mapping
    assert f"Tracked as {m['TODO-002']}." in _read(cfg, STUB_REL)
    assert json.loads(_read(cfg, RESEARCH_REL))["description"] == f"Loader work is {m['TODO-002']}."
    assert notes.read_bytes() == f"See {m['TODO-003']} and TODO-017.\r\n".encode("utf-8")
    rewritten = dict(result.rewritten)
    assert rewritten["docs/notes.md"] == 1 and rewritten[STUB_REL] == 1 and rewritten[RESEARCH_REL] == 1
    assert CATALOG_REL not in rewritten
    assert result.unmapped == ("docs/notes.md:1 names TODO-017",)
    written = json.loads(_read(cfg, CATALOG_REL))
    assert written["legacy_ids"] == {"migrated": DAY, "map": m}
    lines = summary_lines(result, False)
    assert lines[0] == "migrated 3 item(s) to stable ids"
    assert f"id TODO-001 -> {m['TODO-001']}" in lines
    assert "rewrote docs/notes.md (1 reference(s))" in lines
    assert lines[-1] == "next: todo_sync.py render, then todo_sync.py check"


def test_apply_leaves_history_and_excluded_paths(make_project) -> None:
    cfg = build(make_project, _legacy_files())
    folders = (cfg.artifacts.plans, cfg.artifacts.reviews, cfg.artifacts.commit_messages,
               cfg.artifacts.summaries, cfg.todo.snapshots.dir)
    kept = [posix(f"{folder}/0001_Old.md") for folder in folders]
    kept.append("vendor/notes.md")
    for rel in kept:
        _write(cfg, rel, "Executed under TODO-001.\n")
    _write(cfg, "vendored.md", "Executed under TODO-001.\n")
    result = apply_migration(cfg, exclude=["vendor\\"], today=DAY)
    for rel in kept:
        assert _read(cfg, rel) == "Executed under TODO-001.\n", rel
        assert rel not in dict(result.rewritten)
    assert dict(result.rewritten)["vendored.md"] == 1
    lines = summary_lines(result, False)
    history = next(line for line in lines if line.startswith("history left as written: "))
    assert posix(cfg.artifacts.reviews) in history and posix(cfg.artifacts.commit_messages) in history


def test_apply_dry_run_writes_nothing(make_project) -> None:
    files = _legacy_files()
    files[STUB_REL] = stub_text() + "\nTracked as TODO-002.\n"
    cfg = build(make_project, files)
    before = {rel: (cfg.project_root / rel).read_bytes() for rel in (CATALOG_REL, STUB_REL)}
    result = apply_migration(cfg, dry_run=True, today=DAY)
    assert {rel: (cfg.project_root / rel).read_bytes() for rel in before} == before
    lines = summary_lines(result, True)
    assert lines[0] == "would migrate 3 item(s) to stable ids"
    assert f"would rewrite {STUB_REL} (1 reference(s))" in lines
    assert not any(line.startswith("next:") for line in lines)


def test_apply_skips_a_file_that_is_not_utf8(make_project) -> None:
    cfg = build(make_project, _legacy_files())
    latin = cfg.project_root / "docs" / "latin.txt"
    latin.parent.mkdir(parents=True, exist_ok=True)
    latin.write_bytes(b"Caf\xe9 TODO-001\n")
    result = apply_migration(cfg, today=DAY)
    assert latin.read_bytes() == b"Caf\xe9 TODO-001\n"
    assert ("docs/latin.txt", "not UTF-8") in result.skipped
    assert "skipped: docs/latin.txt (not UTF-8)" in summary_lines(result, False)


def test_apply_never_rewrites_the_catalog_schema(make_project) -> None:
    files = _legacy_files()
    files[SCHEMA_REL] = {"$schema": DRAFT, "type": "object", "description": "Ranked items (TODO-001 first)."}
    cfg = build(make_project, files)
    before = (cfg.project_root / SCHEMA_REL).read_bytes()
    result = apply_migration(cfg, today=DAY)
    assert (cfg.project_root / SCHEMA_REL).read_bytes() == before
    assert SCHEMA_REL not in dict(result.rewritten)


def test_a_project_schema_that_rejects_stable_ids_refuses(make_project) -> None:
    files = _legacy_files()
    files[SCHEMA_REL] = LEGACY_SCHEMA
    cfg = build(make_project, files)
    before = (cfg.project_root / CATALOG_REL).read_bytes()
    dry = summary_lines(apply_migration(cfg, dry_run=True, today=DAY), True)
    assert any(line.startswith(f"schema: {SCHEMA_REL} rejects the migrated catalog") for line in dry)
    with pytest.raises(TodoSyncError, match=f"{SCHEMA_REL} rejects the migrated catalog"):
        apply_migration(cfg, today=DAY)
    assert (cfg.project_root / CATALOG_REL).read_bytes() == before


def test_a_failed_git_grep_writes_nothing(make_project, monkeypatch) -> None:
    cfg = build(make_project, _legacy_files())
    before = (cfg.project_root / CATALOG_REL).read_bytes()

    def broken(*args, **kwargs):
        raise OSError("git went away")

    monkeypatch.setattr(retire.subprocess, "run", broken)
    with pytest.raises(TodoSyncError, match="git grep failed: git went away"):
        apply_migration(cfg, today=DAY)
    assert (cfg.project_root / CATALOG_REL).read_bytes() == before


def test_a_failed_file_write_leaves_the_map_for_a_rerun(make_project, monkeypatch) -> None:
    cfg = build(make_project, _legacy_files())
    notes = _write(cfg, "docs/notes.md", "See TODO-003.\n")
    real_write = migrate.write_file

    def locked(path: Path, data: bytes) -> None:
        if path.name == "notes.md":
            raise OSError("locked")
        real_write(path, data)

    monkeypatch.setattr(migrate, "write_file", locked)
    with pytest.raises(TodoSyncError, match="not written: docs/notes.md.*rerun migrate-ids"):
        apply_migration(cfg, today=DAY)
    mapping = json.loads(_read(cfg, CATALOG_REL))["legacy_ids"]["map"]
    assert notes.read_text(encoding="utf-8") == "See TODO-003.\n"
    monkeypatch.setattr(migrate, "write_file", real_write)
    apply_migration(cfg, today=DAY)
    assert notes.read_text(encoding="utf-8") == f"See {mapping['TODO-003']}.\n"


def test_rerun_applies_the_stored_map_to_live_files(make_project) -> None:
    cfg = build(make_project, _legacy_files())
    m = apply_migration(cfg, today=DAY).migration.mapping
    late = _write(cfg, "docs/late.md", "Merged later: TODO-002.\n")
    before = (cfg.project_root / CATALOG_REL).read_bytes()
    again = apply_migration(cfg, today="2026-11-10")
    assert again.migration.mapping == {}
    assert late.read_text(encoding="utf-8") == f"Merged later: {m['TODO-002']}.\n"
    assert (cfg.project_root / CATALOG_REL).read_bytes() == before
    lines = summary_lines(again, False)
    assert lines[0] == "migrated 0 item(s) to stable ids"
    assert "rewrote docs/late.md (1 reference(s))" in lines


def test_migrated_catalog_passes_check(make_project) -> None:
    cfg = build(make_project, _legacy_files())
    assert any(f.rule == "T6" for f in check(cfg, rules=CATALOG_RULES).findings)
    apply_migration(cfg, today=DAY)
    assert check(cfg, rules=CATALOG_RULES).findings == ()
    again = apply_migration(cfg, today=DAY)
    assert again.migration.mapping == {} and again.rewritten == ()
