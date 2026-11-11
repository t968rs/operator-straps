"""A relinked plan keeps its lock: the ``relink`` entry re-records the plan JSON's blob.

``relink`` re-points ``base_commit``, which changes the plan JSON. The entry carries the files the lock (or
the last freeze) held, with the plan JSON's new blob, so ``check`` reports no ``drift:`` on a relinked Locked
plan and ``lock`` accepts a relinked Frozen plan once the relink is committed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import git

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_driver_helpers import Run  # noqa: E402
from test_plan_lock import (STEM, advance_main, commit_all, entries, fill, kind_of, plan_rel,  # noqa: E402
                            prefixed, rewrite_base, tag_target)

driver, project, run = helpers.driver, helpers.project, helpers.run  # the shared fixtures, by name
WALK_ROOTS = ()  # walks only a make_project repo


def _worktree_blob(project: Path, rel: str) -> str:
    return git(project, "hash-object", rel)


def test_relink_on_a_locked_plan_reports_no_drift(run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    old = advance_main(project)
    fill(run, project)
    commit_all(project, "freeze plan 0001")
    code, _, err = run("lock", "1")
    assert code == 0, err
    commit_all(project, "lock plan 0001")
    new = rewrite_base(project, old)
    code, _, err = run("relink", "1")
    assert code == 0, err
    entry = entries(fl, project)[-1]
    assert kind_of(entry) == "relink" and entry.new_base == new
    rel = plan_rel(project)
    assert entry.files[rel] == _worktree_blob(project, rel)
    assert fl.state(entries(fl, project)) == fl.LedgerState("locked")
    code, out, err = run("check", "1")
    assert code == 0, err
    assert not prefixed(out + err, "drift: "), out + err


def test_a_relinked_frozen_plan_locks_once_committed(run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    old = advance_main(project)
    fill(run, project)
    commit_all(project, "freeze plan 0001")
    rewrite_base(project, old)
    code, _, err = run("relink", "1")
    assert code == 0, err
    relinked = entries(fl, project)[-1]
    commit_all(project, "relink plan 0001")
    code, _, err = run("lock", "1")
    assert code == 0, err
    lock = entries(fl, project)[-1]
    rel = plan_rel(project)
    assert kind_of(lock) == "lock" and lock.files == relinked.files
    assert git(project, "rev-parse", f"{lock.tree}:{rel}") == relinked.files[rel]
    assert tag_target(project, f"lock/{STEM}/r1.{lock.seq}-tree") == lock.tree
    code, out, err = run("check", "1")
    assert code == 0, err
    assert not prefixed(out + err, "drift: "), out + err
