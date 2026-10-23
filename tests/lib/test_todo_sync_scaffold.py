"""``todo_sync.py init``: the empty catalog and first snapshot a project starts its TODO sync from."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, SNAP_DIR, TODO_DIR, build, config, todo_files  # noqa: E402
from conftest import git  # noqa: E402
from harness_lib.config import load_config  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, check  # noqa: E402
from harness_lib.todo_sync.scaffold import init_catalog, starter_catalog  # noqa: E402

DAY = dt.date(2026, 10, 23)


def test_init_writes_a_catalog_and_snapshot_that_check_clean(make_project) -> None:
    cfg = build(make_project, {})
    result = init_catalog(cfg, DAY)
    assert result.catalog == cfg.project_root / CATALOG_REL
    assert result.snapshot == cfg.project_root / SNAP_DIR / "TODO_Snapshot_2026_1023.md"
    report = check(cfg)
    assert report.findings == ()
    assert "T1" in report.rules_run and "T2" in report.rules_run


def test_starter_catalog_is_empty_and_records_the_commit() -> None:
    catalog = starter_catalog("abc1234", DAY)
    assert catalog["generated"] == "2026-10-23"
    assert catalog["generated_from"]["head_sha"] == "abc1234"
    assert catalog["items"] == catalog["trackers"] == catalog["close_candidates"] == []
    assert catalog["counts"]["items"] == 0
    assert catalog["counts"]["by_loe"] == {"XS": 0, "S": 0, "M": 0, "L": 0, "XL": 0}
    assert set(catalog["ranking_method"]["impact_weights"]) == {
        "silent_wrong_output", "data_correctness", "runtime_failure", "dev_velocity", "maintainability",
        "docs_tooling"}


def test_catalog_head_sha_is_the_current_commit(make_project) -> None:
    cfg = build(make_project, {})
    init_catalog(cfg, DAY)
    written = json.loads((cfg.project_root / CATALOG_REL).read_text(encoding="utf-8"))
    assert written["generated_from"]["head_sha"] == git(cfg.project_root, "rev-parse", "HEAD")


def test_init_refuses_to_overwrite_a_catalog(make_project) -> None:
    cfg = build(make_project, todo_files())
    path = cfg.project_root / CATALOG_REL
    before = path.read_bytes()
    with pytest.raises(TodoSyncError, match="already exists"):
        init_catalog(cfg, DAY)
    assert path.read_bytes() == before


def test_init_needs_the_todo_folder(make_project) -> None:
    cfg = build(make_project, {}, cfg={})
    with pytest.raises(TodoSyncError, match="init needs todo.folder"):
        init_catalog(cfg, DAY)


def test_init_without_a_snapshots_folder_writes_the_catalog_only(make_project) -> None:
    body = config(todo={"folder": TODO_DIR, "snapshots": {"dir": None}})
    cfg = build(make_project, {}, cfg=body)
    result = init_catalog(cfg, DAY)
    assert result.snapshot is None
    assert result.catalog.is_file()


def test_init_needs_a_commit_to_record(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    (root / ".claude").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    (root / ".claude" / "harness.json").write_text(json.dumps(config()), encoding="utf-8")
    with pytest.raises(TodoSyncError, match="git commit"):
        init_catalog(load_config(root), DAY)
    assert not (root / CATALOG_REL).exists()
