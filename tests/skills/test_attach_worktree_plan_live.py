"""a-w rebuilds ``live.js`` in the target for each receipts plan whose files the move lands.

``live.js`` (``harness_lib.plan_live``) is derived and gitignored, so it never moves with the worktree and is
deleted with it. After a successful move (staged, ``--committed`` or ``--continue``), ``attach_worktree.py``
rebuilds it in the target checkout for every frozen receipts plan whose receipts, freeze ledger, plan JSON or
DesignEvolution the move wrote, printing ``live: rebuilt <plans>/<id>/live.js``. A rebuild that fails prints a
``live: warning:`` line naming ``plan.py render <id>`` and the move still exits 0.

Each test builds a ``make_project`` repository whose ``artifacts.plans`` is ``work/plans`` (not the default),
with branch ``main`` checked out in the project and ``wt`` a detached worktree cut the way ``d-w`` cuts one.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

import pytest

from harness_lib import freeze_ledger as fl
from harness_lib import plan_live as pl
from harness_lib import plan_receipts as prt
from harness_lib.plan_enums import RecordSource
from harness_lib.plan_models import ActionItem, Completed, PassedTests, Provenance
from harness_lib.receipt_models import Receipt

pytestmark = pytest.mark.cross_os

PLANS = "work/plans"
NODE = "tests/test_calc_sub.py::test_sub"
_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t"}
_IGNORES = f"{PLANS}/**/.gitignore\nlive.js\n"


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **_GIT_ENV}
    done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env)
    return done.stdout.strip("\n")


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _item(ident: str) -> Dict[str, object]:
    return {"id": ident, "title": "Add sub", "action": "Add sub.", "status": "PENDING",
            "evidence": "not started", "files": ["src/calc.py"],
            "tests": [{"node": NODE, "red": "ImportError"}]}


def _plan_files(plan_id: str, slug: str, ledger: bool = True) -> Dict[str, object]:
    """A frozen receipts plan: its JSON naming its ledger, one ``freeze`` entry and its HTML page."""
    stem = fl.plan_stem(plan_id, slug.lower())
    raw = {"plan_id": plan_id, "plan_created": "2026-11-10", "execution_model": "serial",
           "base_commit": "e" * 40, "ledger": stem, "items": [_item("TASK-1")]}
    files: Dict[str, object] = {f"{PLANS}/{plan_id}_{slug}_ActionPlan.json": raw,
                                f"{PLANS}/{plan_id}_{slug}_PIP.html": "<!DOCTYPE html>\n"}
    if ledger:
        entry = {"kind": "freeze", "round": 1, "seq": 1, "tree": "a" * 40, "at": "2026-11-11T09:30:00+00:00",
                 "base": "e" * 40, "digest": "d" * 64, "records": "receipts"}
        files[f"{PLANS}/{fl.FREEZES_DIR}/{stem}/r1.1-freeze.json"] = entry
    return files


def _write(root: Path, files: Dict[str, object]) -> None:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body if isinstance(body, str) else json.dumps(body, indent=2), encoding="utf-8")


def _receipt(root: Path, plan_id: str, ident: str) -> None:
    item = ActionItem.model_validate(_item(ident))
    prov = Provenance(source=RecordSource.staged, tree="c" * 40)
    outcome = Completed.of(prov, PassedTests.of([NODE], ["python", "-m", "pytest", NODE]))
    prt.write_receipt(root / PLANS, Receipt.sealed(plan_id, item, outcome=outcome, date="2026-11-12"))


def _live(root: Path, plan_id: str) -> Optional[pl.PlanLive]:
    path = pl.live_path(root / PLANS, plan_id)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return pl.PlanLive.model_validate(json.loads(text[len(pl.LIVE_HEAD):-1]))


@pytest.fixture(scope="module")
def script_path(plugin_root: Path) -> Path:
    return plugin_root / "skills" / "a-w" / "commands" / "attach_worktree.py"


@pytest.fixture()
def repos(make_project, tmp_path: Path) -> dict:
    """The project on ``main`` holding frozen receipts plan 0001 and no ``live.js``; ``wt`` cut from it."""
    files = {".gitignore": _IGNORES, "shared.txt": "one\ntwo\nthree\n", **_plan_files("0001", "Sample")}
    main = make_project(config={"artifacts": {"plans": PLANS}}, files=files)
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "--quiet", "--detach", str(wt), "HEAD")
    return {"main": main, "wt": wt}


def _attach(script_path: Path, repos: dict, *flags: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(script_path), *flags, "--worktree", str(repos["wt"])]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=repos["main"],
                          env={**os.environ, **_GIT_ENV})


def test_a_staged_move_of_a_receipt_rebuilds_live_js_in_the_target(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _receipt(wt, "0001", "TASK-1")
    done = _attach(script_path, repos, "main")
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"live: rebuilt {PLANS}/0001/live.js" in done.stdout.splitlines()
    live = _live(main, "0001")
    assert live is not None and [r.item for r in live.receipts] == ["TASK-1"]
    assert not wt.exists()


def test_a_committed_move_of_a_whole_plan_rebuilds_live_js(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _write(wt, _plan_files("0002", "Other"))
    _receipt(wt, "0002", "TASK-1")
    _commit_all(wt, "freeze and record plan 0002")
    done = _attach(script_path, repos, "main", "--committed")
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert f"live: rebuilt {PLANS}/0002/live.js" in lines
    assert not any("0001/live.js" in line for line in lines), "plan 0001 did not move"
    live = _live(main, "0002")
    assert live is not None and [r.item for r in live.receipts] == ["TASK-1"]


def test_continue_rebuilds_live_js_after_a_resolution(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _receipt(wt, "0001", "TASK-1")
    _write(wt, {"shared.txt": "one\nWT\nthree\n"})
    _commit_all(wt, "worktree edit")
    _write(main, {"shared.txt": "one\nTARGET\nthree\n"})
    _commit_all(main, "target edit")
    assert _attach(script_path, repos, "main").returncode == 2
    _write(wt, {"shared.txt": "one\nRESOLVED\nthree\n"})
    _git(wt, "add", "shared.txt")
    done = _attach(script_path, repos, "--continue")
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"live: rebuilt {PLANS}/0001/live.js" in done.stdout.splitlines()
    live = _live(main, "0001")
    assert live is not None and [r.item for r in live.receipts] == ["TASK-1"]


def test_a_move_that_lands_no_plan_file_rebuilds_nothing(script_path: Path, repos: dict) -> None:
    _write(repos["wt"], {"notes.txt": "notes\n"})
    done = _attach(script_path, repos, "main")
    assert done.returncode == 0, done.stdout + done.stderr
    assert not any(line.startswith("live:") for line in done.stdout.splitlines())
    assert _live(repos["main"], "0001") is None


def test_a_failed_rebuild_warns_and_the_move_still_succeeds(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _write(wt, _plan_files("0003", "Broken", ledger=False))
    _receipt(wt, "0003", "TASK-1")
    done = _attach(script_path, repos, "main")
    assert done.returncode == 0, done.stdout + done.stderr
    warning = [line for line in done.stdout.splitlines() if line.startswith("live: warning:")]
    assert len(warning) == 1 and "0003" in warning[0] and "plan.py render 0003" in warning[0]
    assert f"{PLANS}/0003/receipts/TASK-1.json" in _git(main, "diff", "--cached", "--name-only").splitlines()
    assert not wt.exists()
