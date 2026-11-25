"""``todo_sync.py inbox put --update --spec PATH`` queues field updates of existing items, and ``add --inbox``
applies them with the queued adds in one catalog write, so agents that research items in parallel each queue
their own updates and one drain lands them all.

Run in-process; projects come from ``tests/lib/_todo_helpers.py`` (ids ``todo-p4rs``, ``todo-sp7t``,
``todo-c4ch`` in rank order).
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _todo_helpers import CATALOG_REL, ID2, ID3, build  # noqa: E402
from conftest import PLUGIN_ROOT  # noqa: E402
from harness_lib import catalog_lock  # noqa: E402
from harness_lib.todo_sync import inbox  # noqa: E402

WALK_ROOTS = ()
RISE = {"severity": 5, "impact": "silent_wrong_output"}


@pytest.fixture(scope="module")
def driver():
    script = PLUGIN_ROOT / "scripts" / "todo_sync.py"
    spec = importlib.util.spec_from_file_location("todo_sync_update_driver", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def short_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog_lock, "WAIT_SECONDS", 0.2)


def _parse(driver, argv: List[str]):
    """The parsed arguments; a parser refusal fails the test instead of exiting."""
    try:
        return driver._parser().parse_args(argv)
    except SystemExit:
        raise AssertionError(f"todo_sync.py rejects {argv}") from None


def _run(driver, cfg, capsys, *args: str):
    code = driver.main(["--project", str(cfg.project_root), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def _spec(tmp_path: Path, entries: List[Dict[str, Any]], name: str) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps({"updates": entries}), encoding="utf-8")
    return path


def _catalog(cfg) -> Dict[str, Any]:
    return json.loads(cfg.path(CATALOG_REL).read_text(encoding="utf-8"))


def _item(cfg, item_id: str) -> Dict[str, Any]:
    return next(i for i in _catalog(cfg)["items"] if i["id"] == item_id)


def test_inbox_put_takes_an_update_flag(driver) -> None:
    args = _parse(driver, ["inbox", "put", "--update", "--spec", "update.json"])
    assert args.update is True


def test_put_update_queues_and_add_inbox_applies(driver, make_project, capsys, tmp_path: Path) -> None:
    cfg = build(make_project)
    _parse(driver, ["inbox", "put", "--update", "--spec", "update.json"])
    before = cfg.path(CATALOG_REL).read_bytes()
    spec = _spec(tmp_path, [{"id": ID3, "fields": RISE}], "update.json")
    code, out, err = _run(driver, cfg, capsys, "inbox", "put", "--update", "--spec", str(spec))
    assert code == 0, err
    assert re.fullmatch(r"queued docs/_scratch/todo-inbox/\S+\.json\n", out), out
    assert cfg.path(CATALOG_REL).read_bytes() == before
    code, out, err = _run(driver, cfg, capsys, "add", "--inbox")
    assert code == 0, err
    assert out.strip() == f"inbox: updated 1 item(s): {ID3} (severity, impact); check drift=0"
    assert (_item(cfg, ID3)["severity"], _item(cfg, ID3)["rank"]) == (5, 2)


def _put_in_threads(driver, cfg, specs: List[Path]) -> List[int]:
    """Run one ``inbox put --update`` per spec, each from its own thread, started together."""
    codes: List[int] = []
    gate = threading.Barrier(len(specs))

    def put(spec: Path) -> None:
        gate.wait()
        codes.append(driver.main(["--project", str(cfg.project_root), "inbox", "put", "--update",
                                  "--spec", str(spec)]))

    threads = [threading.Thread(target=put, args=(spec,)) for spec in specs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return codes


def test_parallel_queued_updates_land_in_one_drain_with_drift_0(driver, make_project, capsys,
                                                                tmp_path: Path) -> None:
    cfg = build(make_project)
    _parse(driver, ["inbox", "put", "--update", "--spec", "update.json"])
    first = _spec(tmp_path, [{"id": ID3, "fields": RISE}], "lane-1.json")
    second = _spec(tmp_path, [{"id": ID2, "fields": {"summary": "Narrowed to one file."}}], "lane-2.json")
    assert _put_in_threads(driver, cfg, [first, second]) == [0, 0], capsys.readouterr().err
    capsys.readouterr()
    code, out, err = _run(driver, cfg, capsys, "add", "--inbox")
    assert code == 0, err
    assert out.startswith("inbox: updated 2 item(s): ") and out.strip().endswith("check drift=0")
    assert _item(cfg, ID2)["summary"] == "Narrowed to one file."
    assert inbox.queued(cfg) == []
    code, out, _ = _run(driver, cfg, capsys, "check")
    assert code == 0 and "drift=0" in out


def test_put_update_refuses_a_computed_field(driver, make_project, capsys, tmp_path: Path) -> None:
    cfg = build(make_project)
    _parse(driver, ["inbox", "put", "--update", "--spec", "update.json"])
    spec = _spec(tmp_path, [{"id": ID3, "fields": {"priority": {}}}], "update.json")
    code, _, err = _run(driver, cfg, capsys, "inbox", "put", "--update", "--spec", str(spec))
    assert code == 2 and err.startswith("problem: ") and "sets priority" in err
    assert inbox.queued(cfg) == []


def test_put_update_refuses_file_issue(driver, make_project, capsys, tmp_path: Path) -> None:
    cfg = build(make_project)
    _parse(driver, ["inbox", "put", "--update", "--spec", "update.json"])
    spec = _spec(tmp_path, [{"id": ID3, "fields": RISE}], "update.json")
    code, _, err = _run(driver, cfg, capsys, "inbox", "put", "--update", "--file-issue", "--spec", str(spec))
    assert code == 2 and "--file-issue" in err
    assert inbox.queued(cfg) == []
