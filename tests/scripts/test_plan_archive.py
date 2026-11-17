"""Plan 1021 TASK-2: ``plan.py archive`` folds a plan's driver tags into one archive tag (issue 284).

``archive <id>`` folds every base, receipt and ledger-entry tag of the plan (``freeze``, ``lock``, ``arm``,
``unlock``, ``reopen``, ``relink``) and builds a commit with git plumbing: its tree holds
``receipts/<ITEM>[.n]`` (the tree each receipt tag names, a commit receipt's tree included) and
``freezes/r1.<k>`` (each freeze or lock tree tag), its parents are every distinct base, entry-commit and
receipt commit, and its message maps each folded tag name to its object. It checks that the commit reaches
every folded object before it tags anything, tags the commit ``archive/<stem>/r1`` (``r1-<m>`` once an archive
exists, with the earlier archive as a parent), prints one ``push:`` line naming the archive alone, deletes the
folded local tags and, with ``--remote``, prints the remote delete of every folded tag but the receipt tags,
which never left the clone.

The driver runs in-process through ``main`` with ``--repo``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Set

import pytest
from conftest import git

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_archive_helpers import driver_tags, finished, stem_tags  # noqa: E402
from _plan_driver_helpers import Run  # noqa: E402
from _plan_lock_helpers import STEM, commit_all, entries, prefixed, tag_target  # noqa: E402

driver, project, run = helpers.driver, helpers.project, helpers.run  # the shared fixtures, by name
WALK_ROOTS = ()  # walks only a make_project repo
ARCHIVE = f"archive/{STEM}/r1"
BASE = f"base/{STEM}/r1"
TREE = f"freeze/{STEM}/r1.1-tree"
ENTRY_COMMIT = f"freeze/{STEM}/r1.1-commit"
RECEIPT = f"receipt/{STEM}/TASK-1-commit"


def last_line(project: Path, commit: str) -> str:
    """The last line of the commit message of ``commit``."""
    return git(project, "log", "-1", "--format=%B", commit).splitlines()[-1]


def problem_names(err: str) -> Set[str]:
    """The tag name each ``problem:`` line of ``err`` opens with; ``AssertionError`` when a line is not
    an unreachable-object problem."""
    problems = [line for line in err.splitlines() if line.startswith("problem: ")]
    assert problems and all("not reachable from the archive" in line for line in problems), err
    return {line.split()[1] for line in problems}


def test_archive_folds_every_driver_tag_into_one(driver, run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    from harness_lib import plan_lock as pk
    before = finished(run, project)
    assert sorted(before) == sorted([BASE, TREE, ENTRY_COMMIT, RECEIPT])
    code, out, err = run("archive", "1")
    assert code == 0, err
    commit = tag_target(project, ARCHIVE)
    lines = out.splitlines()
    assert lines[0] == f"archive [done] | plan 0001 | {ARCHIVE} -> {commit[:7]} | folded 4 tag(s)", out
    assert f"tag: {ARCHIVE} -> {commit[:7]}" in lines, out
    assert prefixed(out, "push: ") == [f"push: git push origin {ARCHIVE}"], out
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
    code, out, err = run("archive", "1", "--remote")
    assert code == 0, err
    pushed = sorted(name for name in before if not name.startswith("receipt/"))
    assert prefixed(out, "remote: ") == [f"remote: git push origin --delete {' '.join(pushed)}"], out


def test_archive_again_folds_later_tags_into_r1_2(driver, run: Run, project: Path) -> None:
    finished(run, project)
    code, _, err = run("archive", "1")
    assert code == 0, err
    first = tag_target(project, ARCHIVE)
    code, _, err = run("record", "1", "TASK-1", "--staged")
    assert code == 0, err
    later = driver_tags(project)
    assert sorted(later) == [f"receipt/{STEM}/TASK-1-tree"]
    code, out, err = run("archive", "1")
    assert code == 0, err
    second_name = f"archive/{STEM}/r1-2"
    second = tag_target(project, second_name)
    assert out.splitlines()[0] == (f"archive [done] | plan 0001 | {second_name} -> {second[:7]} | "
                                   "folded 1 tag(s)"), out
    assert git(project, "rev-list", "--parents", "-n", "1", second).split()[1:][0] == first
    assert last_line(project, second) == f"previous: {ARCHIVE} {first}"
    staged = later[f"receipt/{STEM}/TASK-1-tree"]
    assert git(project, "rev-parse", f"{second}:receipts/TASK-1") == staged
    assert stem_tags(project) == [ARCHIVE, second_name] and tag_target(project, ARCHIVE) == first
    third_name = f"archive/{STEM}/r1-3"
    code, _, err = run("record", "1", "TASK-1", "--staged")
    assert code == 0, err
    again = driver_tags(project)
    assert len(again) == 1, sorted(again)
    code, out, err = run("archive", "1")
    assert code == 0, err
    third = tag_target(project, third_name)
    assert out.splitlines()[0] == (f"archive [done] | plan 0001 | {third_name} -> {third[:7]} | "
                                   f"folded {len(again)} tag(s)"), out
    assert git(project, "rev-list", "--parents", "-n", "1", third).split()[1:][0] == second
    assert last_line(project, third) == f"previous: {second_name} {second}"
    assert stem_tags(project) == [ARCHIVE, second_name, third_name]
    code, _, err = run("archive", "1")
    assert code == 1 and "problem: plan 0001 has no driver tags to archive" in err, err
    assert stem_tags(project) == [ARCHIVE, second_name, third_name]


def test_archive_folds_freeze_lock_arm_unlock_and_receipt_commit_tags(driver, run: Run,
                                                                      project: Path) -> None:
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
    code, out, err = run("archive", "1")
    assert code == 0, err
    assert out.splitlines()[0].endswith(f"| folded {len(before)} tag(s)"), out
    assert stem_tags(project) == [ARCHIVE]
    commit = tag_target(project, ARCHIVE)
    message = git(project, "log", "-1", "--format=%B", commit)
    for name, target in before.items():
        assert f"{name} {target}" in message, message
    parents = set(git(project, "rev-list", "--parents", "-n", "1", commit).split()[1:])
    assert {target for name, target in before.items() if name.endswith("-commit")} <= parents


@pytest.mark.parametrize("miss", ["reaches", "held_trees"])
def test_archive_refuses_when_an_object_is_unreachable(driver, run: Run, project: Path,
                                                       monkeypatch: pytest.MonkeyPatch, miss: str) -> None:
    """A folded commit the archive does not reach (``reaches``) or a folded tree its tree does not hold
    (``held_trees``) refuses, naming the matching tags, with nothing tagged or deleted."""
    import harness_lib.freeze_git as fg
    before = finished(run, project)
    if miss == "reaches":
        monkeypatch.setattr(fg, "reaches", lambda repo, tips, obj: False)
        expected = {BASE, ENTRY_COMMIT, RECEIPT}
    else:
        monkeypatch.setattr(fg, "held_trees", lambda repo, tips: set())
        expected = {TREE}
    code, _, err = run("archive", "1")
    assert code == 1, err
    assert problem_names(err) == expected, err
    assert driver_tags(project) == before
    assert git(project, "tag", "--list", "archive/*") == ""


def test_archive_refuses_a_driver_tag_of_no_known_shape(driver, run: Run, project: Path) -> None:
    """A driver tag of no known shape on a commit off every folded history is placed nowhere, so the real
    reach check refuses it with nothing tagged or deleted."""
    finished(run, project)
    odd = f"freeze/{STEM}/r1.1-tree.2"
    orphan = git(project, "commit-tree", "HEAD^{tree}", "-m", "orphan")
    git(project, "tag", "-a", "-m", "odd", odd, orphan)
    before = driver_tags(project)
    code, _, err = run("archive", "1")
    assert code == 1, err
    assert problem_names(err) == {odd}, err
    assert driver_tags(project) == before
    assert git(project, "tag", "--list", "archive/*") == ""
