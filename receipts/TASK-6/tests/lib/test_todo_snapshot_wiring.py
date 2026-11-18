"""Snapshot page wiring: ``Sources.snapshot``, rule T2 and ``init_catalog`` use ``TODO_Snapshot.html``.

Projects come from ``_todo_helpers``; every snapshot the helpers seed is dropped, and the in-sync page is
written at ``PAGE_REL`` when a case needs one.

The T2 cases overlap ``test_todo_sync_rules_todo.py`` on purpose: that file follows ``SNAP_REL`` from the
helpers, while these spell the page name out in ``PAGE_REL``, so a rename of the page fails here even when
the helper constant moves with it. The init case adds the ``todo_live.js`` stamp check that
``test_todo_sync_scaffold.py`` lacks. The ``render_snapshot`` cases pin the write order (page, then stamp,
then the render record), the second render that writes the record alone, and the refusal that writes
nothing when the rendered page carries no stamp.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, SNAP_DIR, build, rule_findings, snapshot_text, todo_files  # noqa: E402
from harness_lib import todo_sync  # noqa: E402
from harness_lib.todo_sync.errors import TodoSyncError  # noqa: E402
from harness_lib.todo_sync.report import write_atomic  # noqa: E402
from harness_lib.todo_sync.scaffold import init_catalog  # noqa: E402
from harness_lib.todo_sync.sources import Sources  # noqa: E402

PAGE_REL = f"{SNAP_DIR}/TODO_Snapshot.html"
DAY = dt.date(2026, 10, 23)


def _files(page: bool = True) -> Dict[str, Any]:
    files = todo_files()
    for rel in [r for r in files if r.startswith(f"{SNAP_DIR}/")]:
        del files[rel]
    if page:
        files[PAGE_REL] = snapshot_text(files[CATALOG_REL])
    return files


def test_sources_reads_the_page(make_project) -> None:
    snap = Sources(build(make_project, _files())).snapshot()
    assert snap is not None and snap.rel == PAGE_REL and snap.header is not None


def test_t2_is_clean_on_an_in_sync_page(make_project) -> None:
    assert rule_findings(build(make_project, _files()), "T2") == []


def test_t2_without_the_page_names_it(make_project) -> None:
    [f] = rule_findings(build(make_project, _files(page=False)), "T2")
    assert (f.severity, f.file) == ("warn", PAGE_REL)
    assert "TODO_Snapshot.html" in f.message


def test_t2_edited_top_row_warns_on_the_page(make_project) -> None:
    files = _files()
    files[CATALOG_REL]["items"][0]["title"] = "Parser drops the first row"
    [f] = rule_findings(build(make_project, files), "T2")
    assert (f.severity, f.file, f.line) == ("warn", PAGE_REL, 1)


def test_init_writes_the_page_and_its_stamp(make_project) -> None:
    cfg = build(make_project, {})
    result = init_catalog(cfg, DAY)
    assert result.snapshot == cfg.project_root / PAGE_REL
    assert (cfg.project_root / SNAP_DIR / "todo_live.js").is_file()


def test_render_write_order_and_the_unchanged_second_render(make_project, monkeypatch) -> None:
    cfg = build(make_project, _files(page=False))
    written: List[str] = []

    def record(path: Path, text: str) -> Path:
        written.append(Path(path).name)
        return write_atomic(path, text)

    monkeypatch.setattr(todo_sync, "write_atomic", record)
    todo_sync.render_snapshot(cfg, DAY)
    assert written == ["TODO_Snapshot.html", "todo_live.js", "render.json"]
    written.clear()
    todo_sync.render_snapshot(cfg, DAY + dt.timedelta(days=1))
    assert written == ["render.json"]
    assert todo_sync.render_record_path(cfg).parent == todo_sync.report_path(cfg).parent


def test_render_without_a_stamp_writes_nothing(make_project, monkeypatch) -> None:
    cfg = build(make_project, _files(page=False))
    monkeypatch.setattr(todo_sync, "page_stamp", lambda text: None)
    with pytest.raises(TodoSyncError, match="no readable stamp"):
        todo_sync.render_snapshot(cfg, DAY)
    folder = cfg.project_root / SNAP_DIR
    assert not (folder / "TODO_Snapshot.html").exists() and not (folder / "todo_live.js").exists()
    assert not todo_sync.render_record_path(cfg).exists()
