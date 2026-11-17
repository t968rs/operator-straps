"""Plan 1021 TASK-3: an archived plan's objects count as tagged (issue 284, driver changes 2 and 3).

Once ``archive/<stem>/r1`` exists, reconcile creates no ``-commit`` tag for an entry whose ``-commit`` tag
an archive folded (``check`` and every other ``PLAN`` command), a refreeze tags no base an archive reaches,
and ``check`` prints no ``untagged:`` line for a base the archive reaches, a tree an archive tree holds or
the commit of a folded entry, and no ``off-history:`` line for a base the archive reaches. An entry written
after the archive is tagged as before and folds into ``r1-2``; an object outside every archive still warns.

The driver runs in-process through ``main`` with ``--repo``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import List

from conftest import git

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_driver_helpers import Result, Run, write_op  # noqa: E402
from _plan_lock_helpers import (PLANNED, STEM, advance_main, commit_all, entries, fill, prefixed,  # noqa: E402
                                rewrite_base)

driver, project, run = helpers.driver, helpers.project, helpers.run  # the shared fixtures, by name
WALK_ROOTS = ()  # walks only a make_project repo
ARCHIVE = f"archive/{STEM}/r1"
QUIET = ("tag: ", "push: ", "untagged: ", "off-history: ")


def stem_tags(project: Path) -> List[str]:
    """Every tag of plan 0001's stem, archive tags included, sorted."""
    return sorted(name for name in git(project, "tag", "--list").splitlines() if f"/{STEM}/" in name)


def finished(run: Run, project: Path) -> None:
    """Freeze and commit plan 0001, tag the freeze commit through ``check``, commit TASK-1 and record it by
    commit, so the plan carries base, freeze tree, freeze commit and receipt tags."""
    fill(run, project)
    commit_all(project, "freeze plan 0001")
    code, _, err = run("check", "1")
    assert code == 0, err
    write_op(project, "sub")
    work = commit_all(project, "TASK-1: sub")
    code, _, err = run("record", "1", "TASK-1", "--sha", work)
    assert code == 0, err


def archive(driver: ModuleType, run: Run, *args: str) -> Result:
    """``plan.py archive <args>``; ``AssertionError`` while plan.py has no archive subcommand."""
    assert "archive" in driver.COMMANDS, "plan.py has no archive subcommand"
    return run("archive", *args)


def loud(text: str) -> List[str]:
    """The reconcile and warning lines of a command's output."""
    return [line for prefix in QUIET for line in prefixed(text, prefix)]


def test_commands_after_archive_tag_nothing_and_warn_nothing(driver, run: Run, project: Path) -> None:
    finished(run, project)
    code, _, err = archive(driver, run, "1")
    assert code == 0, err
    for command in (("check", "1"), ("render", "1"), ("verify", "1")):
        code, out, err = run(*command)
        assert code == 0, err
        assert loud(out + err) == [], (command, out + err)
    assert stem_tags(project) == [ARCHIVE]


def test_a_rewritten_base_the_archive_reaches_is_quiet(driver, run: Run, project: Path) -> None:
    old = advance_main(project)
    finished(run, project)
    code, _, err = archive(driver, run, "1")
    assert code == 0, err
    commit_all(project, "receipts of plan 0001")
    rewrite_base(project, old)
    assert old not in git(project, "rev-list", "HEAD").splitlines()
    code, out, err = run("check", "1")
    assert code == 0, err
    assert loud(out + err) == [], out + err
    assert stem_tags(project) == [ARCHIVE]


def test_an_entry_written_after_the_archive_is_tagged_and_folds_again(driver, run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    finished(run, project)
    code, _, err = archive(driver, run, "1")
    assert code == 0, err
    notes = (project / PLANNED).parent / "notes.txt"
    notes.write_text("a file the archive never saw\n", encoding="utf-8")
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 0, err
    commit_all(project, "refreeze plan 0001")
    _, last = entries(fl, project)
    tree, commit = f"freeze/{STEM}/r1.{last.seq}-tree", f"freeze/{STEM}/r1.{last.seq}-commit"
    code, out, err = run("check", "1")
    assert code == 0, err
    assert any(line.startswith(f"tag: {commit} -> ") for line in prefixed(out, "tag: ")), out
    assert stem_tags(project) == sorted([ARCHIVE, tree, commit])
    code, out, err = archive(driver, run, "1")
    assert code == 0, err
    assert out.splitlines()[0].endswith("| folded 2 tag(s)"), out
    assert stem_tags(project) == [ARCHIVE, f"archive/{STEM}/r1-2"]


def test_a_tree_outside_the_archive_still_warns(driver, run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    finished(run, project)
    code, _, err = archive(driver, run, "1")
    assert code == 0, err
    notes = (project / PLANNED).parent / "notes.txt"
    notes.write_text("a file the archive never saw\n", encoding="utf-8")
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 0, err
    first, last = entries(fl, project)
    assert last.tree != first.tree and "notes.txt" in " ".join(last.files)
    git(project, "tag", "-d", f"freeze/{STEM}/r1.{last.seq}-tree")
    code, out, err = run("check", "1")
    assert code == 0, err
    expected = f"untagged: {last.tree[:7]} (freeze r1.{last.seq} tree)"
    assert prefixed(out + err, "untagged: ") == [expected], out + err
