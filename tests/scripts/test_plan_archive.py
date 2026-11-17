"""Plan 1021 TASK-2: ``plan.py archive`` folds a plan's driver tags into one archive tag (issue 284).

``archive <id>`` folds every base, receipt and ledger-entry tag of the plan (``freeze``, ``lock``, ``arm``,
``unlock``, ``reopen``, ``relink``) and builds a commit with git plumbing: its tree holds
``receipts/<ITEM>[.n]`` (the tree each receipt tag names, a commit receipt's tree included) and
``freezes/r1.<k>`` (each freeze or lock tree tag), its parents are every distinct base, entry-commit and
receipt commit, and its message maps each folded tag name to its object. It checks that the commit reaches every folded object before it tags anything, tags the
commit ``archive/<stem>/r1`` (``r1-<m>`` once an archive exists, with the earlier archive as a parent),
prints one ``push:`` line naming the archive alone, deletes the folded local tags and, with ``--remote``,
prints the remote delete of every folded tag but the receipt tags, which never left the clone.

The driver runs in-process through ``main`` with ``--repo``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, List

import pytest
from conftest import git

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_driver_helpers import Result, Run, write_op  # noqa: E402
from _plan_lock_helpers import STEM, commit_all, entries, fill, prefixed, tag_target  # noqa: E402

driver, project, run = helpers.driver, helpers.project, helpers.run  # the shared fixtures, by name
WALK_ROOTS = ()  # walks only a make_project repo
KINDS = ("base", "receipt", "freeze", "lock", "unlock", "arm", "reopen", "relink")
ARCHIVE = f"archive/{STEM}/r1"
BASE = f"base/{STEM}/r1"
TREE = f"freeze/{STEM}/r1.1-tree"
ENTRY_COMMIT = f"freeze/{STEM}/r1.1-commit"
RECEIPT = f"receipt/{STEM}/TASK-1-commit"


def stem_tags(project: Path) -> List[str]:
    """Every tag of plan 0001's stem, archive tags included, sorted."""
    return sorted(name for name in git(project, "tag", "--list").splitlines() if f"/{STEM}/" in name)


def driver_tags(project: Path) -> Dict[str, str]:
    """``{name: peeled object}`` of plan 0001's base, freeze, lock and receipt tags."""
    return {name: git(project, "rev-parse", f"refs/tags/{name}^{{}}") for name in stem_tags(project)
            if name.split("/", 1)[0] in KINDS}


def finished(run: Run, project: Path) -> Dict[str, str]:
    """Freeze and commit plan 0001, tag the freeze commit through ``check``, commit TASK-1 and record it by
    commit; the driver tags this leaves."""
    fill(run, project)
    commit_all(project, "freeze plan 0001")
    code, _, err = run("check", "1")
    assert code == 0, err
    write_op(project, "sub")
    work = commit_all(project, "TASK-1: sub")
    code, _, err = run("record", "1", "TASK-1", "--sha", work)
    assert code == 0, err
    return driver_tags(project)


def archive(driver: ModuleType, run: Run, *args: str) -> Result:
    """``plan.py archive <args>``; ``AssertionError`` while plan.py has no archive subcommand."""
    assert "archive" in driver.COMMANDS, "plan.py has no archive subcommand"
    return run("archive", *args)


def test_archive_folds_every_driver_tag_into_one(driver, run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    from harness_lib import plan_lock as pk
    before = finished(run, project)
    assert sorted(before) == sorted([BASE, TREE, ENTRY_COMMIT, RECEIPT])
    code, out, err = archive(driver, run, "1")
    assert code == 0, err
    commit = tag_target(project, ARCHIVE)
    lines = out.splitlines()
    assert lines[0] == f"archive [done] | plan 0001 | {ARCHIVE} -> {commit[:7]} | folded 4 tag(s)", out
    assert f"tag: {ARCHIVE} -> {commit[:7]}" in lines and f"push: git push origin {ARCHIVE}" in lines, out
    assert f"deleted: {' '.join(sorted(before))}" in lines, out
    assert not prefixed(out, "remote: ")
    assert git(project, "cat-file", "-t", f"refs/tags/{ARCHIVE}") == "tag"
    assert stem_tags(project) == [ARCHIVE]
    parents = git(project, "rev-list", "--parents", "-n", "1", commit).split()[1:]
    assert sorted(parents) == sorted({before[BASE], before[ENTRY_COMMIT], before[RECEIPT]})
    assert git(project, "ls-tree", "--name-only", commit).splitlines() == ["freezes", "receipts"]
    (entry,) = entries(fl, project)
    assert git(project, "rev-parse", f"{commit}:freezes/r1.1") == entry.tree == before[TREE]
    tested = git(project, "rev-parse", f"{before[RECEIPT]}^{{tree}}")
    assert git(project, "rev-parse", f"{commit}:receipts/TASK-1") == tested
    message = git(project, "log", "-1", "--format=%B", commit)
    for name, target in before.items():
        assert f"{name} {target}" in message, message
    seen = pk._PLAN_TAG.match(ARCHIVE)
    assert seen is not None and seen.group(1) == "0001"


def test_archive_remote_line_skips_receipt_tags(driver, run: Run, project: Path) -> None:
    before = finished(run, project)
    code, out, err = archive(driver, run, "1", "--remote")
    assert code == 0, err
    pushed = sorted(name for name in before if not name.startswith("receipt/"))
    assert prefixed(out, "remote: ") == [f"remote: git push origin --delete {' '.join(pushed)}"], out


def test_archive_again_folds_later_tags_into_r1_2(driver, run: Run, project: Path) -> None:
    finished(run, project)
    code, _, err = archive(driver, run, "1")
    assert code == 0, err
    first = tag_target(project, ARCHIVE)
    code, _, err = run("record", "1", "TASK-1", "--staged")
    assert code == 0, err
    later = driver_tags(project)
    assert sorted(later) == [f"receipt/{STEM}/TASK-1-tree"]
    code, out, err = archive(driver, run, "1")
    assert code == 0, err
    second_name = f"archive/{STEM}/r1-2"
    second = tag_target(project, second_name)
    assert out.splitlines()[0] == (f"archive [done] | plan 0001 | {second_name} -> {second[:7]} | "
                                   "folded 1 tag(s)"), out
    assert first in git(project, "rev-list", "--parents", "-n", "1", second).split()[1:]
    staged = later[f"receipt/{STEM}/TASK-1-tree"]
    assert git(project, "rev-parse", f"{second}:receipts/TASK-1") == staged
    assert stem_tags(project) == [ARCHIVE, second_name] and tag_target(project, ARCHIVE) == first
    code, _, err = archive(driver, run, "1")
    assert code == 1 and "problem: plan 0001 has no driver tags to archive" in err, err
    assert stem_tags(project) == [ARCHIVE, second_name]


def test_archive_folds_the_commit_tags_of_every_entry_kind(driver, run: Run, project: Path) -> None:
    assert "archive" in driver.COMMANDS, "plan.py has no archive subcommand"
    finished(run, project)
    code, _, err = run("lock", "1")
    assert code == 0, err
    commit_all(project, "lock plan 0001")
    code, _, err = run("unlock", "1", "--arm", "design change")
    assert code == 0, err
    commit_all(project, "arm plan 0001")
    code, _, err = run("unlock", "1")
    assert code == 0, err
    commit_all(project, "unlock plan 0001")
    code, _, err = run("check", "1")
    assert code == 0, err
    before = driver_tags(project)
    kinds = {name.split("/", 1)[0] for name in before if name.endswith("-commit")}
    assert {"freeze", "lock", "arm", "unlock", "receipt"} <= kinds, sorted(before)
    code, out, err = archive(driver, run, "1")
    assert code == 0, err
    assert out.splitlines()[0].endswith(f"| folded {len(before)} tag(s)"), out
    assert stem_tags(project) == [ARCHIVE]
    commit = tag_target(project, ARCHIVE)
    message = git(project, "log", "-1", "--format=%B", commit)
    for name, target in before.items():
        assert f"{name} {target}" in message, message
    parents = set(git(project, "rev-list", "--parents", "-n", "1", commit).split()[1:])
    assert {target for name, target in before.items() if name.endswith("-commit")} <= parents


def test_archive_refuses_when_an_object_is_unreachable(driver, run: Run, project: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    import harness_lib.freeze_git as fg
    assert "archive" in driver.COMMANDS, "plan.py has no archive subcommand"
    before = finished(run, project)
    monkeypatch.setattr(fg, "reaches", lambda repo, tips, obj: False)
    code, _, err = archive(driver, run, "1")
    assert code == 1, err
    problems = [line for line in err.splitlines() if line.startswith("problem: ")]
    assert problems and all("not reachable from the archive" in line for line in problems), err
    assert driver_tags(project) == before
    assert git(project, "tag", "--list", "archive/*") == ""
