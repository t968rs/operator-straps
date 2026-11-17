"""Plan 2024 TASK-2: a base with no patch-id counterpart is refused with the off-history end state.

A base squashed or merged away has no commit on HEAD's history with its patch id. ``relink`` without ``--to``
refuses it, and the refusal says the ``off-history:`` warning is then the end state instead of inviting a
guessed ``--to REF`` (issue 313).
"""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import git

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_driver_helpers import Run  # noqa: E402
from _plan_lock_helpers import advance_main, commit_all, fill, prefixed  # noqa: E402

driver, project, run = helpers.driver, helpers.project, helpers.run  # the shared fixtures, by name
WALK_ROOTS = ()  # walks only a make_project repo


def _replace_base(project: Path, old: str) -> str:
    """Replace ``old`` under ``feat-x`` by a commit with other content on the same parent, as a squash that
    folded other work into the base does; nothing on HEAD's history then carries ``old``'s patch id."""
    git(project, "checkout", "-q", "--detach", f"{old}^")
    (project / "docs" / "notes.md").write_text("other notes\n", encoding="utf-8")
    new = commit_all(project, "other notes")
    git(project, "rebase", "-q", "--onto", new, old, "feat-x")
    return new


def test_relink_without_a_counterpart_names_the_off_history_end_state(run: Run, project: Path) -> None:
    old = advance_main(project)
    fill(run, project)
    commit_all(project, "freeze plan 0001")
    _replace_base(project, old)
    assert old not in git(project, "rev-list", "HEAD").splitlines()
    code, out, err = run("relink", "1")
    assert code == 1, out + err
    assert prefixed(err, "problem: no commit on HEAD's history matches base"), err
    assert "off-history" in err, err
    assert "pass --to REF" not in err, err
