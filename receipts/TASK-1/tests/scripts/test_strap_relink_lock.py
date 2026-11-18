"""A relinked Locked strap spec keeps its lock: the ``relink`` entry re-records ``SkillSpec.json``'s blob.

``relink`` re-points ``base``, which changes ``SkillSpec.json``, a file of the lock tree. The entry carries
the lock's files with the spec's new blob, so ``check`` reports no ``drift:`` on the relinked spec. A relinked
spec freezes again in the same round without re-targeting the round's plain base tag.
"""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import git

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _strap_lock_helpers as helpers  # noqa: E402
from _strap_lock_helpers import (LOCKED, NAME, SPEC_REL, STEM, Strap, commit_all, entries,  # noqa: E402
                                 kind_of, ok, peeled, refused)

# the shared fixtures, by name
driver, project, strap, piped = helpers.driver, helpers.project, helpers.strap, helpers.piped
prepared, frozen = helpers.prepared, helpers.frozen


def test_relink_on_a_locked_spec_reports_no_drift(frozen: str, strap: Strap, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    old = git(project, "rev-parse", "HEAD")
    ok(strap("reopen", NAME))
    ok(strap("freeze", NAME))
    commit_all(project)
    ok(strap("lock", NAME))
    commit_all(project)
    new = git(project, "commit-tree", f"{old}^{{tree}}", "-p", f"{old}^", "-m", "work, reworded")
    git(project, "rebase", "-q", "--onto", new, old)
    ok(strap("relink", NAME))
    entry = entries(fl, project)[-1]
    assert kind_of(entry) == "relink" and entry.new_base == new
    assert entry.files[SPEC_REL] == git(project, "hash-object", SPEC_REL)
    assert fl.state(entries(fl, project)) == fl.LedgerState("locked")
    assert LOCKED in refused(strap("freeze", NAME, "--refreeze"))
    out = ok(strap("check", NAME))
    assert not [line for line in out.splitlines() if line.strip().startswith("drift: ")], out


def test_a_relinked_spec_freezes_in_the_same_round(frozen: str, strap: Strap, project: Path) -> None:
    """The relink tag ``r2-2`` holds the new base, so the freeze requests no ``base/<stem>/r2``."""
    from harness_lib import freeze_ledger as fl
    old_base = git(project, "rev-parse", "HEAD")
    ok(strap("reopen", NAME))
    git(project, "commit", "--amend", "-q", "-m", "work, reworded")
    new_base = git(project, "rev-parse", "HEAD")
    ok(strap("relink", NAME))
    before = git(project, "tag", "--list", f"base/{STEM}/*").splitlines()
    out = ok(strap("freeze", NAME))
    assert not [line for line in out.splitlines() if line.strip().startswith("tag: base/")], out
    assert git(project, "tag", "--list", f"base/{STEM}/*").splitlines() == before
    assert peeled(project, f"base/{STEM}/r2", "commit") == old_base
    assert peeled(project, f"base/{STEM}/r2-2", "commit") == new_base
    entry = entries(fl, project)[-1]
    assert kind_of(entry) == "freeze" and entry.round == 2 and entry.base == new_base
