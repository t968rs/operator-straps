"""Plan 2021 TASK-3: an archived plan's objects count as tagged (issue 284, driver changes 2 and 3).

Once ``archive/<stem>/r1`` exists, reconcile creates no ``-commit`` tag for an entry whose ``-commit`` tag
an archive folded (``check`` and every other ``PLAN`` command), a refreeze tags no base an archive reaches,
and ``check`` prints no ``untagged:`` line for a base the archive reaches, a tree an archive tree holds or
the commit of a folded entry. A base off HEAD's history still prints ``off-history:``, archived or not: it
is the relink cue. An entry written after the archive is tagged as before and folds into ``r1-2``; an
object outside every archive still warns.

The driver runs in-process through ``main`` with ``--repo``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

from conftest import git

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_archive_helpers import finished, stem_tags  # noqa: E402
from _plan_driver_helpers import Run  # noqa: E402
from _plan_lock_helpers import (PLANNED, STEM, advance_main, commit_all, entries,  # noqa: E402
                                prefixed, rewrite_base)

driver, project, run = helpers.driver, helpers.project, helpers.run  # the shared fixtures, by name
WALK_ROOTS = ()  # walks only a make_project repo
ARCHIVE = f"archive/{STEM}/r1"
QUIET = ("tag: ", "push: ", "untagged: ", "off-history: ")


def loud(text: str) -> List[str]:
    """The reconcile and warning lines of a command's output."""
    return [line for prefix in QUIET for line in prefixed(text, prefix)]


def archive_link(project: Path, name: str) -> Tuple[List[str], str]:
    """The parents and the last message line of the commit the archive tag ``name`` peels to."""
    commit = git(project, "rev-parse", f"refs/tags/{name}^{{commit}}")
    parents = git(project, "rev-list", "--parents", "-n", "1", commit).split()[1:]
    return parents, git(project, "log", "-1", "--format=%B", commit).splitlines()[-1]


def test_commands_after_archive_tag_nothing_and_warn_nothing(driver, run: Run, project: Path) -> None:
    finished(run, project)
    code, _, err = run("archive", "1")
    assert code == 0, err
    for command in (("check", "1"), ("render", "1"), ("verify", "1")):
        code, out, err = run(*command)
        assert code == 0, err
        assert loud(out + err) == [], (command, out + err)
    assert stem_tags(project) == [ARCHIVE]


def test_a_rewritten_base_the_archive_reaches_still_cues_relink(driver, run: Run, project: Path) -> None:
    old = advance_main(project)
    finished(run, project)
    code, _, err = run("archive", "1")
    assert code == 0, err
    commit_all(project, "receipts of plan 0001")
    rewrite_base(project, old)
    assert old not in git(project, "rev-list", "HEAD").splitlines()
    code, out, err = run("check", "1")
    assert code == 0, err
    assert loud(out + err) == [f"off-history: {old[:7]} (base r1)"], out + err
    assert stem_tags(project) == [ARCHIVE]


def test_an_entry_written_after_the_archive_is_tagged_and_folds_again(
        driver, run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    finished(run, project)
    code, _, err = run("archive", "1")
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
    code, out, err = run("archive", "1")
    assert code == 0, err
    assert out.splitlines()[0].endswith("| folded 2 tag(s)"), out
    assert stem_tags(project) == [ARCHIVE, f"archive/{STEM}/r1-2"]
    first = git(project, "rev-parse", f"{ARCHIVE}^{{commit}}")
    second = git(project, "rev-parse", f"archive/{STEM}/r1-2^{{commit}}")
    parents, last_line = archive_link(project, f"archive/{STEM}/r1-2")
    assert parents[:1] == [first] and last_line == f"previous: {ARCHIVE} {first}", (parents, last_line)
    notes.write_text("a second file the archive never saw\n", encoding="utf-8")
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 0, err
    commit_all(project, "second refreeze plan 0001")
    code, _, err = run("check", "1")
    assert code == 0, err
    code, _, err = run("archive", "1")
    assert code == 0, err
    assert stem_tags(project) == [ARCHIVE, f"archive/{STEM}/r1-2", f"archive/{STEM}/r1-3"]
    parents, last_line = archive_link(project, f"archive/{STEM}/r1-3")
    expected = f"previous: archive/{STEM}/r1-2 {second}"
    assert parents[:1] == [second] and last_line == expected, (parents, last_line)


def test_a_dropped_older_archive_tag_keeps_its_objects_archived(driver, run: Run, project: Path) -> None:
    """With only ``r1-2`` left, its ``previous:`` chain keeps the first archive's objects counted, so check
    re-tags nothing and warns nothing."""
    finished(run, project)
    code, _, err = run("archive", "1")
    assert code == 0, err
    notes = (project / PLANNED).parent / "notes.txt"
    notes.write_text("a file the archive never saw\n", encoding="utf-8")
    code, _, err = run("freeze", "1", "--refreeze")
    assert code == 0, err
    commit_all(project, "refreeze plan 0001")
    code, _, err = run("check", "1")
    assert code == 0, err
    code, _, err = run("archive", "1")
    assert code == 0, err
    git(project, "tag", "-d", ARCHIVE)
    code, out, err = run("check", "1")
    assert code == 0, err
    assert loud(out + err) == [], out + err
    assert stem_tags(project) == [f"archive/{STEM}/r1-2"]


def test_a_tree_outside_the_archive_still_warns(driver, run: Run, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    finished(run, project)
    code, _, err = run("archive", "1")
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
