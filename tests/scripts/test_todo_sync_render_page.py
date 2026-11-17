"""``todo_sync.py render`` writes one snapshot page, ``TODO_Snapshot.html``, and its ``todo_live.js`` stamp.

Each case runs the driver as a subprocess against a ``make_project`` tree built from
``tests/lib/_todo_helpers.py``; every snapshot the helpers seed is dropped first, so the page under test is
the one render writes.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _todo_helpers import (CATALOG_REL, ID1, ID2, SNAP_DIR, TODO_DIR, config, snapshot_text,  # noqa: E402
                           stub_text, todo_files)
from conftest import GIT_ENV, PLUGIN_ROOT  # noqa: E402
from harness_lib.todo_sync.snapshot_html import page_stamp  # noqa: E402

SCRIPT = PLUGIN_ROOT / "scripts" / "todo_sync.py"
PAGE = "TODO_Snapshot.html"
LIVE = "todo_live.js"
REPORT_REL = Path(".claude") / "state" / "harness" / "todo-sync" / "report.json"
BETA_STUB = "docs/RESEARCH/Beta/_IMPL_TODO.md"
WALK_ROOTS = ()  # walks only the make_project snapshot folder


def _run(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_ENV}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=120)


def _files() -> Dict[str, Any]:
    files = todo_files()
    for rel in [r for r in files if r.startswith(f"{SNAP_DIR}/")]:
        del files[rel]
    return files


def _render(make_project, files: Dict[str, Any], body: Optional[Dict[str, Any]] = None) -> Path:
    root = make_project(config() if body is None else body, files=files)
    done = _run(["render", "--date", "2026-10-21"], root)
    assert done.returncode == 0, done.stderr
    assert Path(done.stdout.strip()) == root / SNAP_DIR / PAGE
    return root


def _rows(root: Path) -> List[str]:
    text = (root / SNAP_DIR / PAGE).read_text(encoding="utf-8")
    return re.findall(r'<tr class="row".*?</tr>', text, re.S)


def _findings(root: Path) -> List[Dict[str, Any]]:
    return json.loads((root / REPORT_REL).read_text(encoding="utf-8"))["findings"]


def test_render_writes_the_page_and_its_stamp_and_t2_is_clean(make_project) -> None:
    root = _render(make_project, _files())
    page = (root / SNAP_DIR / PAGE).read_text(encoding="utf-8")
    first = page.splitlines()[0]
    assert first.startswith(f"<!-- todo-snapshot source={CATALOG_REL} top=10 rows_sha256=")
    assert first.endswith(" rendered=2026-10-21 -->")
    live = (root / SNAP_DIR / LIVE).read_text(encoding="utf-8")
    stamp = page_stamp(page)
    assert stamp is not None
    assert json.loads(live[len("window.TODO_LIVE = "):-2]) == {"stamp": stamp, "rendered": "2026-10-21"}
    assert not list((root / SNAP_DIR).glob("*.md"))
    assert _run(["check", "--rules", "T2"], root).returncode == 0 and _findings(root) == []


def test_a_second_render_rewrites_the_one_page(make_project) -> None:
    root = _render(make_project, _files())
    done = _run(["render", "--date", "2026-10-22"], root)
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in (root / SNAP_DIR).iterdir()) == [PAGE, LIVE]
    assert "rendered=2026-10-22" in (root / SNAP_DIR / PAGE).read_text(encoding="utf-8").splitlines()[0]


def test_rows_link_their_stubs_by_position(make_project) -> None:
    files = _files()
    files[BETA_STUB] = stub_text("beta-cache")
    items = files[CATALOG_REL]["items"]
    items[1]["sources"].append({"type": "impl_stub", "ref": BETA_STUB, "item": "Beta part"})
    items[2].update(id=ID2, sources=[{"type": "impl_stub", "ref": BETA_STUB, "item": "Beta"}])
    rows = _rows(_render(make_project, files))
    assert '<a class="stub" href="../../Alpha/_IMPL_TODO.md">1</a>' in rows[1]
    assert '<a class="stub" href="../../Beta/_IMPL_TODO.md">2</a>' in rows[1]
    assert '<a class="stub" href="../../Beta/_IMPL_TODO.md">1</a>' in rows[2]
    assert '<a class="stub"' not in rows[0]
    assert f'<td class="c-id"><span class="id">{ID2}</span></td>' in rows[2]


def test_items_past_top_n_go_to_the_folded_rest_table(make_project) -> None:
    files = _files()
    files[BETA_STUB] = stub_text("beta-cache")
    items = files[CATALOG_REL]["items"]
    items[2].update(id=ID2, sources=[{"type": "impl_stub", "ref": BETA_STUB, "item": "Beta"}])
    items.reverse()  # catalog order opposite to rank order: the driver must sort before the cut
    root = _render(make_project, files, config({"folder": TODO_DIR, "top_n": 1}))
    page = (root / SNAP_DIR / PAGE).read_text(encoding="utf-8")
    top, rest = page.split('<details id="rest">', 1)
    assert len(re.findall(r'<tr class="row"', top)) == 1 and "<h2>Top 1</h2>" in top
    assert re.findall(r'data-rank="(\d+)"', top) == ["1"]
    assert re.findall(r'data-rank="(\d+)"', rest) == ["2", "3"]
    assert "<h2>Remaining 2 items</h2>" in rest
    rows = re.findall(r'<tr class="row".*?</tr>', rest, re.S)
    assert len(rows) == 2 and '<a class="stub" href="../../Beta/_IMPL_TODO.md">1</a>' in rows[1]
    assert f'<td class="c-id"><span class="id">{ID2}</span></td>' in rows[1]
    assert page.splitlines()[0].startswith(f"<!-- todo-snapshot source={CATALOG_REL} top=1 ")
    assert _run(["check", "--rules", "T2"], root).returncode == 0 and _findings(root) == []


def test_gh_and_tracker_cells(make_project) -> None:
    rows = _rows(_render(make_project, _files()))
    assert '<a href="https://github.com/example/widgets/issues/11">#11</a>' in rows[0]
    assert "tracker #101" in rows[1]
    assert "<a " not in rows[1].split("tracker", 1)[1]


def test_configured_gh_repo_links_a_tracker_without_a_source_url(make_project) -> None:
    body = config({"folder": TODO_DIR, "gh": {"repo": "o/r"}})
    rows = _rows(_render(make_project, _files(), body))
    assert '<a href="https://github.com/o/r/issues/101">#101</a>' in rows[1]


def test_render_tolerates_malformed_link_fields(make_project) -> None:
    files = _files()
    items = files[CATALOG_REL]["items"]
    items[0].update(sources=5, catalog_entry_ids=5)
    items[1]["id"] = [ID2]
    rows = _rows(_render(make_project, files))
    assert len(rows) == 3 and ID1 in rows[0]
    assert '<a class="stub"' not in rows[1]


def _title(root: Path) -> str:
    text = (root / SNAP_DIR / PAGE).read_text(encoding="utf-8")
    return re.search(r"<title>(.*?)</title>", text).group(1)


def test_the_title_opens_with_the_gh_repo_name(make_project) -> None:
    root = _render(make_project, _files(), config({"folder": TODO_DIR, "gh": {"repo": "o/widgets"}}))
    assert _title(root) == "widgets | TODO Snapshot (2026-10-21)"


def test_without_a_gh_repo_the_title_opens_with_the_checkout_folder(make_project) -> None:
    root = _render(make_project, _files())
    assert _title(root) == f"{root.resolve().name} | TODO Snapshot (2026-10-21)"


def test_render_with_null_stub_name(make_project) -> None:
    root = _render(make_project, _files(), config({"folder": TODO_DIR, "stub_name": None}))
    assert '<a class="stub" href="../../Alpha/_IMPL_TODO.md">1</a>' in _rows(root)[1]


def test_the_name_pattern_no_longer_gates_render(make_project) -> None:
    body = config()
    body["todo"]["snapshots"] = {"name_pattern": r"Snap_(?P<date>\d{8})\.md"}
    root = _render(make_project, _files(), body)
    assert (root / SNAP_DIR / PAGE).is_file()


def test_t2_reads_the_page_not_a_dated_markdown_snapshot(make_project) -> None:
    files = _files()
    files[f"{SNAP_DIR}/TODO_Snapshot_2026_1019.md"] = snapshot_text(files[CATALOG_REL])
    root = make_project(config(), files=files)
    assert _run(["check", "--rules", "T2"], root).returncode == 0
    assert [(f["rule"], f["file"]) for f in _findings(root)] == [("T2", f"{SNAP_DIR}/{PAGE}")]


def test_a_title_quoting_the_loader_keeps_the_live_stamp(make_project) -> None:
    files = _files()
    files[CATALOG_REL]["items"][0]["title"] = "Rename var TODO_PAGE = {}; in the loader"
    root = _render(make_project, files)
    page = (root / SNAP_DIR / PAGE).read_text(encoding="utf-8")
    # page_stamp reads the trailing loader script, not a body title that quotes its assignment.
    stamp = page_stamp(page) or ""
    assert re.fullmatch(r"[0-9a-f]{64}", stamp)
    live = (root / SNAP_DIR / LIVE).read_text(encoding="utf-8")
    assert json.loads(live[len("window.TODO_LIVE = "):-2])["stamp"] == stamp
