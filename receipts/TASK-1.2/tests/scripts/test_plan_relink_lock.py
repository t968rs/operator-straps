"""A relinked plan keeps its lock: the ``relink`` entry re-records the plan JSON's blob.

``relink`` re-points ``base_commit``, which changes the plan JSON. The entry carries the files the lock (or
the last freeze) held, with the plan JSON's new blob, so ``check`` reports no ``drift:`` on a relinked Locked
plan and ``lock`` accepts a relinked Frozen plan once the relink is committed. A relinked plan freezes again:
the base tag of the relink already holds the base, so the freeze requests no ``base/<stem>/r1`` and leaves
that name on the old base. A hand-named plan file's title freezes to a stem the ``ledger`` pattern accepts.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from conftest import git

from harness_lib import plan_doc as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_driver_helpers import Run, plan_file, read_plan  # noqa: E402
from _plan_lock_helpers import (STEM, advance_main, commit_all, entries, fill, kind_of, plan_rel,  # noqa: E402
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


def _base_tags(project: Path) -> List[str]:
    return git(project, "tag", "--list", f"base/{STEM}/*").splitlines()


def _freeze_adds_no_base_tag(run: Run, project: Path, old: str, new: str, *args: str) -> None:
    """``freeze 1 *args`` succeeds and leaves the base tags as the relink left them."""
    before = _base_tags(project)
    code, out, err = run("freeze", "1", *args)
    assert code == 0, err
    assert not prefixed(out, "tag: base/"), out
    assert _base_tags(project) == before
    assert tag_target(project, f"base/{STEM}/r1") == old
    assert tag_target(project, f"base/{STEM}/r1-2") == new


def test_a_relinked_frozen_plan_refreezes(run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    old = advance_main(project)
    fill(run, project)
    commit_all(project, "freeze plan 0001")
    new = rewrite_base(project, old)
    code, _, err = run("relink", "1")
    assert code == 0, err
    _freeze_adds_no_base_tag(run, project, old, new, "--refreeze")
    assert [kind_of(e) for e in entries(fl, project)] == ["freeze", "relink", "freeze"]


def test_a_relinked_locked_plan_refreezes_after_unlock(run: Run, project: Path) -> None:
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
    commit_all(project, "relink plan 0001")
    assert run("unlock", "1", "--arm", "rebased")[0] == 0
    assert run("unlock", "1")[0] == 0
    _freeze_adds_no_base_tag(run, project, old, new, "--refreeze")
    assert fl.state(entries(fl, project)) == fl.LedgerState.frozen


def test_a_plan_relinked_before_its_first_freeze_freezes(run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    old = advance_main(project)
    fill(run, project, freeze=False)
    commit_all(project, "plan 0001 items")
    new = rewrite_base(project, old)
    code, _, err = run("relink", "1")
    assert code == 0, err
    _freeze_adds_no_base_tag(run, project, old, new)
    assert kind_of(entries(fl, project)[-1]) == "freeze"


def test_a_hand_named_plan_file_freezes_to_a_loadable_ledger(run: Run, project: Path) -> None:
    """A title with a dot (``0001_v1.2_fix_ActionPlan.json``) gives a stem the ``ledger`` pattern accepts."""
    fill(run, project, freeze=False)
    source = plan_file(project)
    source.rename(source.with_name("0001_v1.2_fix_ActionPlan.json"))
    commit_all(project, "plan 0001 renamed by hand")
    code, _, err = run("freeze", "1")
    assert code == 0, err
    assert read_plan(project)["ledger"] == "plan/0001-v1-2-fix"
    assert pd.load_plan(plan_file(project)).frozen is not None
    code, _, err = run("check", "1")
    assert code == 0, err
