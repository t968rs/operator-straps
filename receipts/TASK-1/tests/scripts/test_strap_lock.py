"""``strap.py`` freeze ledger entries, tree tags and the Locked state (plan 1015, STR-1).

Asymmetric: ``SkillSpec.json`` keeps ``frozen``, ``rounds`` and ``authored``; the ledger, one file per entry
under ``<artifacts.plans>/freezes/skill/<name>/r<N>.<k>-<kind>.json``, records each freeze, lock, reopen and
relink, and the Locked state lives only there. ``freeze`` writes a ``freeze`` entry and tags its tree after
preflighting every tag name, ``lock`` refuses a stale spec and otherwise writes ``lock`` and tags the lock
tree, a Locked spec refuses green runs and refreezes, ``reopen`` writes ``reopen`` and tags the new base, a
spec frozen before the ledger gets history entries at its refreeze, ``relink`` re-points a rewritten base,
a scenario tree (``freeze_git.SCENARIO_MARKER`` at the root) creates no tags, and ``check`` reports a
ledger whose last freeze disagrees with the spec stamp.

The driver runs in-process through ``main`` with ``--repo``; specs are built through ``strap.py api``, as
in ``tests/scripts/test_strap_reopen.py``.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import List

from conftest import git

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _strap_lock_helpers as helpers  # noqa: E402
from _strap_lock_helpers import (LOCKED, NAME, PLANNED_TEST, PLANS, SKILL, SPEC_REL, STEM, Strap,  # noqa: E402
                                 commit_all, entries, kind_of, ledger_folder, ok, peeled, read_spec,
                                 refused, skill_text, write)

# the shared fixtures, by name
driver, project, strap, piped = helpers.driver, helpers.project, helpers.strap, helpers.piped
prepared, frozen = helpers.prepared, helpers.frozen
HEX40 = re.compile(r"^[0-9a-f]{40}$")
LEGACY = f"legacy: {NAME} has no ledger; one starts at its next freeze --refreeze, reopen or relink"


def spec_text(project: Path) -> str:
    return (project / SPEC_REL).read_text(encoding="utf-8")


def tags(project: Path) -> List[str]:
    return git(project, "tag", "--list").splitlines()


def tree_paths(project: Path, tree: str) -> List[str]:
    return sorted(git(project, "ls-tree", "-r", "--name-only", tree).splitlines())


def drop_ledger(fl: ModuleType, project: Path) -> None:
    """Remove the ledger folder and every tag, committed: a spec frozen before the ledger existed."""
    shutil.rmtree(ledger_folder(fl, project))
    for tag in tags(project):
        git(project, "tag", "-d", tag)
    commit_all(project)


def lock_committed(strap: Strap, project: Path) -> None:
    ok(strap("lock", NAME))
    commit_all(project)


def test_freeze_writes_ledger_entry_and_tags_tree(prepared: Path, strap: Strap) -> None:
    from harness_lib import freeze_ledger as fl
    folder = ledger_folder(fl, prepared)
    assert folder == prepared / PLANS / "freezes" / "skill" / NAME
    out = ok(strap("freeze", NAME))
    assert (folder / "r1.1-freeze.json").is_file()
    [entry] = entries(fl, prepared)
    assert kind_of(entry) == "freeze" and entry.round == 1 and entry.seq == 1 and not entry.history
    assert fl.entry_name(entry) == "r1.1-freeze.json"
    assert entry.tree is not None and HEX40.match(entry.tree), entry.tree
    assert entry.skill_hash == read_spec(prepared)["frozen"]["skill_hash"]
    tag = f"freeze/{STEM}/r1.1-tree"
    assert peeled(prepared, tag, "tree") == entry.tree
    assert git(prepared, "cat-file", "-t", tag) == "tag"
    paths = tree_paths(prepared, entry.tree)
    assert SKILL in paths and PLANNED_TEST in paths and SPEC_REL not in paths
    assert sorted(entry.files) == paths
    assert all(HEX40.match(blob) for blob in entry.files.values()), entry.files
    assert re.search(rf"^tag: {re.escape(tag)} -> {entry.tree[:7]}", out, re.MULTILINE), out
    assert re.search(rf"^push: git push origin .*{re.escape(tag)}", out, re.MULTILINE), out


def _legacy_round_two(fl: ModuleType, strap: Strap, project: Path) -> str:
    """Reopen, freeze round 2 and commit, then drop the ledger and tags; returns round 2's base."""
    base = git(project, "rev-parse", "HEAD")
    ok(strap("reopen", NAME))
    ok(strap("freeze", NAME))
    commit_all(project)
    drop_ledger(fl, project)
    assert read_spec(project)["base"] == base
    return base


def test_freeze_refuses_on_tag_collision(frozen: str, strap: Strap, project: Path) -> None:
    """Tree tags take a seq past every existing tag, so the collision is on a fixed name: the base tag
    the migration of a legacy round-2 spec creates (spec: Migration, Tags > Collision)."""
    from harness_lib import freeze_ledger as fl
    _legacy_round_two(fl, strap, project)
    root_commit = git(project, "rev-list", "--max-parents=0", "HEAD")
    tag = f"base/{STEM}/r2"
    git(project, "tag", "-a", tag, "-m", "foreign", root_commit)
    before = spec_text(project)
    err = refused(strap("freeze", NAME, "--refreeze"))
    assert tag in err, err
    assert not ledger_folder(fl, project).exists() or entries(fl, project) == []
    assert spec_text(project) == before
    assert peeled(project, tag, "commit") == root_commit
    assert tags(project) == [tag]


def test_lock_refuses_stale_then_locks(frozen: str, strap: Strap, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    write(project, SKILL, skill_text("Changed after the freeze."))
    refused(strap("lock", NAME))
    assert [kind_of(e) for e in entries(fl, project)] == ["freeze"]
    assert git(project, "tag", "--list", "lock/*") == ""
    ok(strap("freeze", NAME, "--refreeze"))
    second = entries(fl, project)[-1]
    assert kind_of(second) == "freeze" and second.round == 1 and second.seq == 2
    assert peeled(project, f"freeze/{STEM}/r1.2-tree", "tree") == second.tree
    commit_all(project)
    ok(strap("lock", NAME))
    entry = entries(fl, project)[-1]
    assert kind_of(entry) == "lock" and entry.round == 1 and entry.seq == 3
    assert (ledger_folder(fl, project) / "r1.3-lock.json").is_file()
    assert entry.tree is not None and HEX40.match(entry.tree), entry.tree
    assert peeled(project, f"lock/{STEM}/r1.{entry.seq}-tree", "tree") == entry.tree
    paths = tree_paths(project, entry.tree)
    assert SPEC_REL in paths and SKILL in paths and sorted(entry.files) == paths
    assert fl.state(entries(fl, project)) == fl.LedgerState("locked")


def test_locked_spec_refuses_green_run_and_refreeze(frozen: str, strap: Strap, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    lock_committed(strap, project)
    before = spec_text(project)
    count = len(entries(fl, project))
    err = refused(strap("run", NAME, "B1", "--arm", "green"))
    assert LOCKED in err, err
    err = refused(strap("freeze", NAME, "--refreeze"))
    assert LOCKED in err, err
    assert len(entries(fl, project)) == count
    assert spec_text(project) == before


def test_reopen_on_locked_spec_writes_reopen_and_tags_base(frozen: str, strap: Strap,
                                                           project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    lock_committed(strap, project)
    head = git(project, "rev-parse", "HEAD")
    ok(strap("reopen", NAME))
    found = entries(fl, project)
    assert [kind_of(e) for e in found][-2:] == ["lock", "reopen"]
    assert found[-1].tree is None and found[-1].base == head
    assert peeled(project, f"base/{STEM}/r2", "commit") == head
    spec = read_spec(project)
    assert spec["frozen"] is None and spec["base"] == head
    assert [r["frozen"]["skill_hash"] for r in spec["rounds"]] == [frozen]
    ok(strap("freeze", NAME))
    entry = entries(fl, project)[-1]
    assert kind_of(entry) == "freeze" and entry.round == 2
    assert peeled(project, f"freeze/{STEM}/r2.{entry.seq}-tree", "tree") == entry.tree


def test_reopen_empties_the_locked_files(frozen: str, strap: Strap, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    ok(strap("lock", NAME))
    commit_all(project)
    assert SPEC_REL in fl.locked_files(entries(fl, project), PLANS)
    ok(strap("reopen", NAME))
    assert fl.locked_files(entries(fl, project), PLANS) == []


def test_legacy_spec_gets_history_entries_on_refreeze(frozen: str, strap: Strap, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    drop_ledger(fl, project)
    out = ok(strap("check", NAME))
    assert LEGACY in [line.strip() for line in out.splitlines()], out
    ok(strap("freeze", NAME, "--refreeze"))
    history, current = entries(fl, project)
    assert kind_of(history) == "freeze" and history.history is True and history.tree is None
    assert (history.round, history.seq) == (1, 1) and history.skill_hash == frozen
    assert kind_of(current) == "freeze" and not current.history
    assert (current.round, current.seq) == (1, 2)
    assert current.tree is not None and HEX40.match(current.tree), current.tree
    assert current.skill_hash == read_spec(project)["frozen"]["skill_hash"]
    assert peeled(project, f"freeze/{STEM}/r1.2-tree", "tree") == current.tree
    assert f"freeze/{STEM}/r1.1-tree" not in tags(project)


def test_relink_repoints_base_and_tags(frozen: str, strap: Strap, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    old_base = git(project, "rev-parse", "HEAD")
    ok(strap("reopen", NAME))
    git(project, "commit", "--amend", "-q", "-m", "work, reworded")
    new_base = git(project, "rev-parse", "HEAD")
    assert new_base != old_base
    ok(strap("relink", NAME))
    assert read_spec(project)["base"] == new_base
    entry = entries(fl, project)[-1]
    assert kind_of(entry) == "relink" and entry.tree is None
    assert (entry.old_base, entry.new_base, entry.match) == (old_base, new_base, "patch-id")
    assert peeled(project, f"base/{STEM}/r2-2", "commit") == new_base
    assert peeled(project, f"base/{STEM}/r2", "commit") == old_base


def test_scenario_tree_creates_no_tags(prepared: Path, strap: Strap) -> None:
    from harness_lib import freeze_git as fg
    from harness_lib import freeze_ledger as fl
    write(prepared, fg.SCENARIO_MARKER, "scenario\n")
    out = ok(strap("freeze", NAME))
    assert tags(prepared) == []
    assert not [line for line in out.splitlines() if line.startswith(("tag:", "push:"))], out
    assert [kind_of(e) for e in entries(fl, prepared)] == ["freeze"]


def test_check_reports_ledger_spec_mismatch(frozen: str, strap: Strap, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    out = ok(strap("check", NAME))
    assert not [line for line in out.splitlines() if line.strip().startswith("ledger:")], out
    last = entries(fl, project)[-1]
    doctored = {**last.model_dump(mode="json"), "seq": last.seq + 1, "skill_hash": "f" * 64}
    fl.write_entry(ledger_folder(fl, project), fl.LedgerEntry.model_validate(doctored))
    out = ok(strap("check", NAME))
    assert [line for line in out.splitlines() if line.strip().startswith("ledger:")], out
