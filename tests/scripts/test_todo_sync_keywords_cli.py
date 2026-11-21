"""``todo_sync.py suggest-keyword`` and ``todo_sync.py keywords`` (plan 2028), run in-process.

``suggest-keyword --spec PATH`` prints one ``item <n>: <guess|none>`` line per drafted item, for the agent to
read before ``inbox put``. ``keywords`` is the one-time migration: it writes each confident guess into the
catalog under the catalog lock and prints what it set; ``--dry-run`` writes nothing.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _todo_helpers import CATALOG_REL, ID1, build, todo_files  # noqa: E402
from conftest import PLUGIN_ROOT  # noqa: E402

WALK_ROOTS = ()


@pytest.fixture(scope="module")
def driver():
    script = PLUGIN_ROOT / "scripts" / "todo_sync.py"
    spec = importlib.util.spec_from_file_location("todo_sync_keywords_driver", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(driver, cfg, capsys, *args: str):
    try:
        code = driver.main(["--project", str(cfg.project_root), *args])
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def test_suggest_keyword_prints_one_line_per_item(driver, make_project, tmp_path: Path, capsys) -> None:
    cfg = build(make_project)
    spec = tmp_path / "add.json"
    spec.write_text(json.dumps({"items": [
        {"title": "merge-commit-msg: fall back", "files": []},
        {"title": "Two modules", "files": ["src/one.py", "src/two.py"]},
    ]}), encoding="utf-8")
    code, out, _err = _run(driver, cfg, capsys, "suggest-keyword", "--spec", str(spec))
    assert (code, out.splitlines()) == (0, ["item 1: merge-commit-msg", "item 2: none"])


def test_keywords_dry_run_writes_nothing_and_the_real_run_writes(driver, make_project, capsys) -> None:
    files = todo_files()
    files[CATALOG_REL]["items"][0]["files"] = ["src/parser.py"]
    cfg = build(make_project, files)
    path = cfg.path(CATALOG_REL)
    before = path.read_bytes()
    code, out, _err = _run(driver, cfg, capsys, "keywords", "--dry-run")
    assert code == 0 and f"set {ID1}: parser" in out and path.read_bytes() == before
    code, out, _err = _run(driver, cfg, capsys, "keywords")
    assert code == 0 and out.splitlines()[0] == "keywords: set 1, left 2 without one"
    assert json.loads(path.read_text(encoding="utf-8"))["items"][0]["keyword"] == "parser"
