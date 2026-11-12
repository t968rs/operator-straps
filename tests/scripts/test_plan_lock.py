"""Plan 1015 PLN-1: ``plan.py`` keeps the freeze stamp in a per-entry ledger, locks a freeze, tags both.

``freeze`` writes ``<plans>/freezes/plan/<id>-<slug>/r1.<k>-freeze.json``, sets the plan's static ``ledger``
field and tags the scoped tree; every tag name is preflighted, so a foreign tag on a fixed name (the base tag
a migration creates) refuses the command before anything is written. ``lock`` accepts only a committed
freeze; a Locked plan refuses ``freeze --refreeze`` until ``unlock --arm REASON`` and a plain ``unlock``.
``new`` tags the base commit and numbers past plan ids seen on other branches and in tags; ``check`` tags the
commit that added an entry and reports drift of a Locked plan; a plan with an in-file stamp migrates to the
ledger on refreeze; ``relink`` re-points a rewritten ``base_commit``; ``record`` tags the tested code locally.

The driver runs in-process through ``main`` with ``--repo``.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from conftest import git

from harness_lib import plan_doc as pd
from harness_lib.plan_enums import RecordScheme

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_driver_helpers import PLANS, Run, plan_file, read_plan, write_op, write_plan  # noqa: E402
from _plan_lock_helpers import (PLANNED, STEM, advance_main, commit_all, entries, fill, kind_of,  # noqa: E402
                                ledger_folder, plan_rel, prefixed, rewrite_base, tag_target)

driver, project, run = helpers.driver, helpers.project, helpers.run  # the shared fixtures, by name
WALK_ROOTS = ()  # walks only a make_project repo
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
LEDGER_DIR = f"{PLANS}/freezes/{STEM}"
LEGACY_DATE = "2026-11-01"
LEGACY = "legacy: plan 0001 keeps an in-file stamp; migrates at its next refreeze"


def lock_committed(run: Run, project: Path) -> str:
    """Fill and freeze plan 0001, commit the freeze, lock it; the commit holding the freeze entry."""
    fill(run, project)
    sha = commit_all(project, "freeze plan 0001")
    code, _, err = run("lock", "1")
    assert code == 0, err
    return sha


def value_of(field: Any) -> Any:
    return getattr(field, "value", field)


def tags(project: Path) -> List[str]:
    return git(project, "tag", "--list").splitlines()


@pytest.mark.cross_os
def test_freeze_writes_ledger_and_tree_tag(run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    out = fill(run, project)
    folder = ledger_folder(fl, project)
    assert folder == project / LEDGER_DIR and (folder / "r1.1-freeze.json").is_file()
    plan = read_plan(project)
    assert "frozen" not in plan and plan["ledger"] == STEM
    (entry,) = entries(fl, project)
    assert (kind_of(entry), entry.round, entry.seq, entry.history) == ("freeze", 1, 1, False)
    assert HEX40.match(entry.tree) and HEX64.match(entry.digest)
    assert value_of(entry.records) == "receipts" and entry.base == plan["base_commit"]
    assert sorted(entry.files) == sorted([plan_rel(project), PLANNED]) and not entry.ignored
    listed = git(project, "ls-tree", "-r", "--name-only", entry.tree).splitlines()
    assert sorted(listed) == sorted(entry.files)
    for path, blob in entry.files.items():
        assert git(project, "rev-parse", f"{entry.tree}:{path}") == blob, path
    name = f"freeze/{STEM}/r1.1-tree"
    assert tag_target(project, name) == entry.tree
    assert git(project, "cat-file", "-t", f"refs/tags/{name}") == "tag"
    assert f"tag: {name} -> {entry.tree[:7]}" in out, out
    pushes = prefixed(out, "push: git push origin ")
    assert pushes and name in pushes[0], out


def as_legacy(project: Path) -> Dict[str, Any]:
    """Stamp the unfrozen plan in its file, as ``freeze`` did before the ledger; drop every tag; commit.

    The stamp names HEAD and its tree, dated LEGACY_DATE, with the receipts digest of the plan as it
    stands. Returns the stamp.
    """
    plan = read_plan(project)
    plan.pop("ledger", None)
    plan["frozen"] = None
    write_plan(project, plan)
    digest = pd.frozen_digest(pd.load_plan(plan_file(project)), RecordScheme.receipts)
    plan["frozen"] = {"commit": git(project, "rev-parse", "HEAD"),
                      "tree": git(project, "rev-parse", "HEAD^{tree}"), "date": LEGACY_DATE,
                      "digest": digest, "records": "receipts"}
    write_plan(project, plan)
    for tag in tags(project):
        git(project, "tag", "-d", tag)
    commit_all(project, "plan 0001 frozen before the ledger")
    return plan["frozen"]


def test_freeze_refuses_on_tag_collision(run: Run, project: Path) -> None:
    """The next ``r1.<k>`` counts past existing tags, so the collision is on a fixed name: the base tag the
    migration refreeze of a legacy plan creates (spec: Tags, Collision; Migration)."""
    from harness_lib import freeze_ledger as fl
    fill(run, project, freeze=False)
    as_legacy(project)
    foreign = git(project, "rev-parse", "HEAD")
    assert foreign != read_plan(project)["base_commit"]
    tag = f"base/{STEM}/r1"
    git(project, "tag", "-a", tag, "-m", "foreign", foreign)
    before = plan_file(project).read_bytes()
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 1, err
    named = [line for line in err.splitlines() if tag in line]
    assert named and named[0].startswith("problem: "), err
    assert not ledger_folder(fl, project).exists()
    assert plan_file(project).read_bytes() == before
    assert git(project, "status", "--porcelain") == ""
    assert tag_target(project, tag) == foreign and tags(project) == [tag]


def test_lock_requires_committed_freeze(run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    fill(run, project)
    code, _, err = run("lock", "1")
    assert code == 1 and "problem: " in err, err
    assert [kind_of(e) for e in entries(fl, project)] == ["freeze"]
    assert git(project, "tag", "--list", "lock/*") == ""
    commit_all(project, "freeze plan 0001")
    code, out, err = run("lock", "1")
    assert code == 0, err
    freeze, lock = entries(fl, project)
    assert (kind_of(lock), lock.round, lock.seq) == ("lock", 1, 2)
    assert (ledger_folder(fl, project) / "r1.2-lock.json").is_file()
    assert lock.tree == freeze.tree and lock.files == freeze.files
    name = f"lock/{STEM}/r1.{lock.seq}-tree"
    assert tag_target(project, name) == lock.tree
    assert f"tag: {name} -> {lock.tree[:7]}" in out, out
    assert fl.state(entries(fl, project)) == fl.LedgerState.locked


def test_unlock_needs_arm_then_allows_refreeze(run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    lock_committed(run, project)
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 1 and "unlock" in err, err
    code, _, err = run("unlock", "1")
    assert code == 1 and "--arm" in err, err
    assert [kind_of(e) for e in entries(fl, project)] == ["freeze", "lock"]
    code, _, err = run("unlock", "1", "--arm", "design change")
    assert code == 0, err
    arm = entries(fl, project)[-1]
    assert (kind_of(arm), arm.seq, arm.tree, arm.reason) == ("arm", 3, None, "design change")
    assert fl.state(entries(fl, project)) == fl.LedgerState.armed
    assert run("freeze", "1", "--refreeze")[0] == 1
    code, _, err = run("unlock", "1")
    assert code == 0, err
    assert kind_of(entries(fl, project)[-1]) == "unlock"
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 0, err
    found = entries(fl, project)
    assert [kind_of(e) for e in found] == ["freeze", "lock", "arm", "unlock", "freeze"]
    assert (found[-1].round, found[-1].seq) == (1, 5)
    assert tag_target(project, f"freeze/{STEM}/r1.5-tree") == found[-1].tree
    assert fl.state(found) == fl.LedgerState.frozen


def test_new_number_skips_branches_and_tags(run: Run, project: Path) -> None:
    git(project, "checkout", "-q", "-b", "other")
    elsewhere = project / PLANS / "0001_Other_work_ActionPlan.json"
    elsewhere.parent.mkdir(parents=True, exist_ok=True)
    elsewhere.write_text("{}\n", encoding="utf-8")
    commit_all(project, "plan 0001 on another branch")
    git(project, "checkout", "-q", "feat-x")
    git(project, "tag", "-a", "freeze/plan/0002-ghost/r1.1-tree", "-m", "held", "HEAD")
    code, out, err = run("new", "Third plan")
    assert code == 0, err
    assert out.startswith("new [done] | plan 0003"), out
    folder = project / PLANS
    assert not list(folder.glob("000[12]_*")) and list(folder.glob("0003_*_ActionPlan.json"))
    assert tag_target(project, "base/plan/0003-third-plan/r1") == read_plan(project)["base_commit"]


def test_check_reconciles_commit_tag_and_reports_drift(run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    fill(run, project)
    sha = commit_all(project, "freeze plan 0001")
    added = git(project, "log", "--diff-filter=A", "--format=%H", "--", f"{LEDGER_DIR}/r1.1-freeze.json")
    assert added == sha
    code, out, err = run("check", "1")
    assert code == 0, err
    name = f"freeze/{STEM}/r1.1-commit"
    assert tag_target(project, name) == sha
    assert f"tag: {name} -> {sha[:7]}" in out, out
    code, _, err = run("lock", "1")
    assert code == 0, err
    lock = entries(fl, project)[-1]
    commit_all(project, "lock plan 0001")
    plan_file(project).write_text(json.dumps(read_plan(project), indent=4), encoding="utf-8")
    code, out, err = run("check", "1")
    assert code == 0, err
    drift = prefixed(out + err, "drift: ")
    assert drift and drift[0].startswith(f"drift: {plan_rel(project)} differs from "), out + err
    assert f"lock/{STEM}/r1.{lock.seq}-" in drift[0], drift


def test_legacy_plan_migrates_on_refreeze(run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    fill(run, project, freeze=False)
    stamp = as_legacy(project)
    code, out, err = run("check", "1")
    assert code == 0, err
    assert LEGACY in out + err, out + err
    code, _, err = run("lock", "1")
    assert code == 1 and "--refreeze" in err, err
    assert not ledger_folder(fl, project).exists()
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 0, err
    history, fresh = entries(fl, project)
    assert (kind_of(history), history.round, history.seq) == ("freeze", 1, 1)
    assert history.history is True and history.tree is None
    assert history.digest == stamp["digest"] and value_of(history.records) == "receipts"
    assert str(history.at).startswith(LEGACY_DATE), history.at
    assert (kind_of(fresh), fresh.round, fresh.seq, fresh.history) == ("freeze", 1, 2, False)
    assert fresh.tree is not None and HEX40.match(fresh.tree)
    plan = read_plan(project)
    assert "frozen" not in plan and plan["ledger"] == STEM
    assert tag_target(project, f"freeze/{STEM}/r1.2-tree") == fresh.tree
    assert f"freeze/{STEM}/r1.1-tree" not in tags(project)
    assert tag_target(project, f"base/{STEM}/r1") == plan["base_commit"]


def test_relink_repoints_base_commit(run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    old = advance_main(project)
    fill(run, project)
    assert read_plan(project)["base_commit"] == old
    commit_all(project, "freeze plan 0001")
    new = rewrite_base(project, old)
    history = git(project, "rev-list", "HEAD").splitlines()
    assert old not in history and new in history
    _, out, err = run("check", "1")
    assert prefixed(out + err, f"off-history: {old[:7]}"), out + err
    code, _, err = run("relink", "1")
    assert code == 0, err
    assert read_plan(project)["base_commit"] == new
    entry = entries(fl, project)[-1]
    assert (kind_of(entry), entry.tree) == ("relink", None)
    assert (entry.old_base, entry.new_base, value_of(entry.match)) == (old, new, "patch-id")
    assert tag_target(project, f"base/{STEM}/r1-2") == new
    assert tag_target(project, f"base/{STEM}/r1") == old


@pytest.mark.cross_os
def test_record_tags_receipt_locally(run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    fill(run, project)
    assert fl.plan_stem("0001", "add-operators") == STEM
    write_op(project, "sub")
    git(project, "add", "src/calc.py", "tests/test_calc_sub.py")
    tested = git(project, "write-tree")
    code, out, err = run("record", "1", "TASK-1", "--staged")
    assert code == 0, err
    name = f"receipt/{STEM}/TASK-1-tree"
    assert tag_target(project, name) == tested
    assert git(project, "cat-file", "-t", f"refs/tags/{name}") == "tag"
    assert f"tag: {name} -> {tested[:7]}" in out, out
    pushes = prefixed(out + err, "push:")
    assert not [line for line in pushes if "receipt/" in line], pushes
