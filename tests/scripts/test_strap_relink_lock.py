"""A relinked Locked strap spec keeps its lock: the ``relink`` entry re-records ``SkillSpec.json``'s blob.

``relink`` re-points ``base``, which changes ``SkillSpec.json``, a file of the lock tree. The entry carries
the lock's files with the spec's new blob, so ``check`` reports no ``drift:`` on the relinked spec.
"""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import git

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_strap_lock as base  # noqa: E402
from test_strap_lock import (LOCKED, NAME, PLANS, SPEC_REL, Strap, commit_all, entries,  # noqa: E402
                             kind_of, ok, refused)

# the shared fixtures, by name
driver, project, strap, piped = base.driver, base.project, base.strap, base.piped
prepared, frozen = base.prepared, base.frozen


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


def test_reopen_releases_the_lock_guard(frozen: str, strap: Strap, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    ok(strap("lock", NAME))
    commit_all(project)
    assert SPEC_REL in fl.locked_files(entries(fl, project), PLANS)
    ok(strap("reopen", NAME))
    assert fl.locked_files(entries(fl, project), PLANS) == []
