"""The catalog lock as ``scripts/todo_sync.py`` uses it: every catalog-writing subcommand holds it, a lease
serializes a todo-editor run, ``lease release`` recounts, and the inbox subcommands queue and drain items.

Run in-process; projects come from ``tests/lib/_todo_helpers.py`` (issues 11, 101, 102 and 103 are recorded).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _todo_helpers import CATALOG_REL, ID3, LEGACY_CATALOG, build, rule_findings, todo_files  # noqa: E402
from conftest import PLUGIN_ROOT  # noqa: E402
from harness_lib import catalog_lock  # noqa: E402
from harness_lib.todo_sync import inbox, locking  # noqa: E402

NEW_ID = r"todo-[2-9a-hjkmnp-z]{4}"
WALK_ROOTS = ()


@pytest.fixture(scope="module")
def driver():
    script = PLUGIN_ROOT / "scripts" / "todo_sync.py"
    spec = importlib.util.spec_from_file_location("todo_sync_lock_driver", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def short_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog_lock, "WAIT_SECONDS", 0.2)


def _item(issue: int) -> Dict[str, Any]:
    return {"issue": issue, "url": f"https://github.com/example/widgets/issues/{issue}",
            "title": f"New problem {issue}", "kind": "bug", "summary": "The parser skips a row.",
            "proposed_change": "Read every row.", "impact": "silent_wrong_output", "severity": 5,
            "why_ranked": "Computed from ranking_method.",
            "blast_radius": {"level": "S", "reasoning": "One module.", "consumers": []},
            "loe": {"size": "S", "reasoning": "Small."}}


def _plant(cfg, owner: str = "another writer") -> Path:
    """A live write lock held by another writer on the project's catalog."""
    path = locking.lock_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "owner": owner,
                                "mode": "write", "acquired": time.time()}), encoding="utf-8")
    return path


def _run(driver, cfg, capsys, *args: str):
    code = driver.main(["--project", str(cfg.project_root), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def _token(out: str) -> str:
    found = re.search(r"^lease: (\S+)$", out, re.MULTILINE)
    assert found, out
    return found.group(1)


def test_the_lock_file_sits_under_the_state_dir(make_project) -> None:
    cfg = build(make_project)
    path = locking.lock_path(cfg)
    assert path.parent == cfg.path(".claude/state/harness/locks")
    assert path.name.endswith(".lock") and "RepoToDo.json" in path.name


def test_a_lease_admits_its_holder_and_refuses_every_other_writer(driver, make_project, capsys) -> None:
    cfg = build(make_project)
    code, out, _ = _run(driver, cfg, capsys, "lease", "acquire", "--owner", "todo-editor retire")
    assert code == 0
    token = _token(out)
    code, _, err = _run(driver, cfg, capsys, "refresh")
    assert code == 2 and "todo-editor retire" in err
    code, _, err = _run(driver, cfg, capsys, "retire", ID3, "--lease", token)
    assert code == 0, err
    code, _, err = _run(driver, cfg, capsys, "retire", ID3, "--lease", "wrong")
    assert code == 2 and "token" in err


def test_release_recounts_a_hand_appended_close_candidate(driver, make_project, capsys) -> None:
    cfg = build(make_project)
    token = _token(_run(driver, cfg, capsys, "lease", "acquire", "--owner", "todo-editor retire")[1])
    catalog = json.loads(cfg.path(CATALOG_REL).read_text(encoding="utf-8"))
    catalog.setdefault("close_candidates", []).append(
        {"number": 77, "title": "Done", "url": "https://github.com/example/widgets/issues/77",
         "current_state": "LIKELY_RESOLVED", "evidence": "abc1234", "recommended_action": "close",
         "related_todo_ids": []})
    cfg.path(CATALOG_REL).write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    assert rule_findings(cfg, "T9")
    code, out, err = _run(driver, cfg, capsys, "lease", "release", token)
    assert code == 0, err
    assert out.splitlines()[0].startswith("lease released")
    assert rule_findings(cfg, "T9") == []
    assert not locking.lock_path(cfg).exists()


def test_release_frees_the_lease_when_the_catalog_cannot_load(driver, make_project, capsys) -> None:
    cfg = build(make_project)
    token = _token(_run(driver, cfg, capsys, "lease", "acquire", "--owner", "todo-editor retire")[1])
    cfg.path(CATALOG_REL).write_text("{", encoding="utf-8")
    code, _, err = _run(driver, cfg, capsys, "lease", "release", token)
    assert code == 2 and "problem:" in err
    assert not locking.lock_path(cfg).exists()


def test_break_removes_a_lease_and_names_its_holder(driver, make_project, capsys) -> None:
    cfg = build(make_project)
    _run(driver, cfg, capsys, "lease", "acquire", "--owner", "todo-editor split")
    code, out, _ = _run(driver, cfg, capsys, "lease", "break")
    assert code == 0 and "todo-editor split" in out
    assert not locking.lock_path(cfg).exists()
    code, out, _ = _run(driver, cfg, capsys, "lease", "break")
    assert code == 0 and out.strip() == "lease: none held"


WRITERS: List[List[str]] = [["refresh"], ["retire", ID3]]


@pytest.mark.parametrize("args", WRITERS, ids=lambda a: a[0])
def test_a_writer_refuses_while_another_holds_the_lock(driver, make_project, capsys, args: List[str]) -> None:
    cfg = build(make_project)
    _plant(cfg)
    before = cfg.path(CATALOG_REL).read_bytes()
    code, _, err = _run(driver, cfg, capsys, *args)
    assert code == 2 and "another writer" in err
    assert cfg.path(CATALOG_REL).read_bytes() == before


def test_add_with_a_spec_holds_the_lock(driver, make_project, capsys, tmp_path: Path) -> None:
    cfg = build(make_project)
    _plant(cfg)
    spec = tmp_path / "add.json"
    spec.write_text(json.dumps({"items": [_item(9)]}), encoding="utf-8")
    code, _, err = _run(driver, cfg, capsys, "add", "--spec", str(spec))
    assert code == 2 and "another writer" in err


def test_split_holds_the_lock(driver, make_project, capsys, tmp_path: Path) -> None:
    cfg = build(make_project)
    _plant(cfg)
    spec = tmp_path / "split.json"
    spec.write_text(json.dumps({"parts": [{"title": "a"}, {"title": "b"}]}), encoding="utf-8")
    code, _, err = _run(driver, cfg, capsys, "split", ID3, "--spec", str(spec))
    assert code == 2 and "another writer" in err


def test_init_holds_the_lock(driver, make_project, capsys) -> None:
    cfg = build(make_project, {})
    _plant(cfg)
    code, _, err = _run(driver, cfg, capsys, "init")
    assert code == 2 and "another writer" in err
    assert not cfg.path(CATALOG_REL).exists()


def test_migrate_ids_holds_the_lock(driver, make_project, capsys) -> None:
    files = todo_files()
    files[CATALOG_REL] = LEGACY_CATALOG
    cfg = build(make_project, files)
    _plant(cfg)
    code, _, err = _run(driver, cfg, capsys, "migrate-ids")
    assert code == 2 and "another writer" in err


def test_add_inbox_holds_the_lock_and_keeps_the_queued_file(driver, make_project, capsys,
                                                            tmp_path: Path) -> None:
    cfg = build(make_project)
    folder = inbox.inbox_dir(cfg)
    folder.mkdir(parents=True)
    queued = folder / "20261113T000001Z-aaaaaa.json"
    queued.write_text(json.dumps({"items": [_item(9)]}), encoding="utf-8")
    _plant(cfg)
    code, _, err = _run(driver, cfg, capsys, "add", "--inbox")
    assert code == 2 and "another writer" in err
    assert queued.is_file()


def test_an_empty_inbox_needs_no_lock(driver, make_project, capsys) -> None:
    cfg = build(make_project)
    _plant(cfg)
    code, out, err = _run(driver, cfg, capsys, "add", "--inbox")
    assert code == 0 and out.strip() == "inbox: empty", err


def test_a_dry_run_takes_no_lock(driver, make_project, capsys) -> None:
    cfg = build(make_project)
    _plant(cfg)
    code, _, err = _run(driver, cfg, capsys, "retire", ID3, "--dry-run")
    assert code == 0, err


def test_inbox_put_queues_and_add_inbox_drains(driver, make_project, capsys, tmp_path: Path) -> None:
    cfg = build(make_project)
    spec = tmp_path / "add.json"
    spec.write_text(json.dumps({"items": [_item(9), _item(12)]}), encoding="utf-8")
    before = cfg.path(CATALOG_REL).read_bytes()
    code, out, err = _run(driver, cfg, capsys, "inbox", "put", "--spec", str(spec))
    assert code == 0, err
    queued = [line for line in out.splitlines() if line.startswith("queued ")]
    assert len(queued) == 2 and all("docs/_scratch/todo-inbox/" in line for line in queued)
    assert cfg.path(CATALOG_REL).read_bytes() == before
    code, out, err = _run(driver, cfg, capsys, "add", "--inbox")
    assert code == 0, err
    [line] = out.splitlines()
    assert re.match(rf"inbox: added 2 item\(s\): {NEW_ID} \(#9\), {NEW_ID} \(#12\)", line), line
    assert list(inbox.inbox_dir(cfg).glob("*.json")) == []
    code, out, _ = _run(driver, cfg, capsys, "add", "--inbox")
    assert code == 0 and out.strip() == "inbox: empty"


def test_inbox_put_refusal_exits_2(driver, make_project, capsys, tmp_path: Path) -> None:
    cfg = build(make_project)
    spec = tmp_path / "add.json"
    spec.write_text(json.dumps({"items": [_item(11)]}), encoding="utf-8")
    code, _, err = _run(driver, cfg, capsys, "inbox", "put", "--spec", str(spec))
    assert code == 2 and "problem: issue #11 is already in the catalog" in err


def test_add_takes_a_spec_or_the_inbox(driver, make_project, capsys) -> None:
    cfg = build(make_project)
    with pytest.raises(SystemExit):
        driver.main(["--project", str(cfg.project_root), "add"])
