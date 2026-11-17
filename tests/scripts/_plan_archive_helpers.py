"""Shared helpers of the plan archive tests (``test_plan_archive.py``, ``test_plan_archive_check.py``).

Each helper drives ``plan.py`` through the ``run`` fixture of ``_plan_driver_helpers`` or reads the tags of
plan 0001 in a ``make_project`` repo.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from conftest import git

from _plan_driver_helpers import Run, write_op
from _plan_lock_helpers import STEM, commit_all, fill

KINDS = ("base", "receipt", "freeze", "lock", "unlock", "arm", "reopen", "relink")


def stem_tags(project: Path) -> List[str]:
    """Every tag of plan 0001's stem, archive tags included, sorted."""
    return sorted(name for name in git(project, "tag", "--list").splitlines() if f"/{STEM}/" in name)


def driver_tags(project: Path) -> Dict[str, str]:
    """``{name: peeled object}`` of plan 0001's base, freeze, lock and receipt tags."""
    return {name: git(project, "rev-parse", f"refs/tags/{name}^{{}}") for name in stem_tags(project)
            if name.split("/", 1)[0] in KINDS}


def finished(run: Run, project: Path) -> Dict[str, str]:
    """Freeze and commit plan 0001, tag the freeze commit through ``check``, commit TASK-1 and record it by
    commit; the driver tags this leaves (base, freeze tree, freeze commit and receipt)."""
    fill(run, project)
    commit_all(project, "freeze plan 0001")
    code, _, err = run("check", "1")
    assert code == 0, err
    write_op(project, "sub")
    work = commit_all(project, "TASK-1: sub")
    code, _, err = run("record", "1", "TASK-1", "--sha", work)
    assert code == 0, err
    return driver_tags(project)
