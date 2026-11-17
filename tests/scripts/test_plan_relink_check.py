"""Plan 2024 TASK-1: ``relink`` refuses a base where the plan's anchors or sweeps fail (issue 313).

``check`` reads anchors and sweeps at ``base_commit`` once an item is done, and a freeze before that point
requires them at the base, so ``relink`` runs the same claims at the candidate base before it saves the plan
JSON, writes the ``relink`` entry or tags the new base. A refusal names each failing claim on a
``problem: at base <sha7>:`` line and leaves the plan JSON, the ledger and the base tags as they were. The
claims run whether or not an item is done; the two anchor tests pin that one rule on a plan with an item
recorded done and on one with none. A rewritten base with the same tree passes both kinds of claim.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

from conftest import git

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_driver_helpers as helpers  # noqa: E402
from _plan_driver_helpers import Run, plan_file, read_plan, write_op, write_plan  # noqa: E402
from _plan_lock_helpers import STEM, commit_all, entries, fill, prefixed, rewrite_base  # noqa: E402

driver, project, run = helpers.driver, helpers.project, helpers.run  # the shared fixtures, by name
WALK_ROOTS = ()  # walks only a make_project repo
MARKER = "# relink marker"


def _advance_main(project: Path) -> Tuple[str, str]:
    """Commit ``docs/notes.md`` and a marker line in ``src/calc.py`` on ``main``, fast-forward ``feat-x``.

    Returns ``(root, base)``: the commit before them, which lacks both, and the commit that adds them.
    """
    root = git(project, "rev-parse", "main")
    git(project, "checkout", "-q", "main")
    (project / "docs" / "notes.md").write_text("notes\n", encoding="utf-8")
    calc = project / "src" / "calc.py"
    calc.write_text(calc.read_text(encoding="utf-8") + f"\n{MARKER}\n", encoding="utf-8")
    base = commit_all(project, "notes and marker")
    git(project, "checkout", "-q", "feat-x")
    git(project, "merge", "-q", "--ff-only", "main")
    return root, base


def _frozen_plan(run: Run, project: Path, anchor: bool, sweep: bool) -> None:
    """Plan 0001 with TASK-1, frozen and committed; ``anchor`` adds a claim on ``docs/notes.md`` and
    ``sweep`` a sweep that classifies the marker line in ``src/calc.py``."""
    fill(run, project, freeze=False)
    plan = read_plan(project)
    if anchor:
        plan["items"][0]["anchors"].append({"at": "docs/notes.md:1", "expect": "notes"})
    if sweep:
        plan["sweeps"] = [{"id": "S1", "pattern": "relink marker",
                           "hits": {"src/calc.py": "the marker line main added"}}]
    write_plan(project, plan)
    code, _, err = run("freeze", "1")
    assert code == 0, err
    commit_all(project, "freeze plan 0001")


def _record_done(run: Run, project: Path) -> None:
    """Implement TASK-1 in the index and record it COMPLETE (a receipt on a receipts plan)."""
    write_op(project, "sub")
    git(project, "add", "src/calc.py", "tests/test_calc_sub.py")
    code, _, err = run("record", "1", "TASK-1", "--staged")
    assert code == 0, err


def _state(project: Path) -> Tuple[str, List[str], List[str]]:
    """The plan JSON text, the ledger entry file names and the base tags of plan 0001."""
    from harness_lib import freeze_ledger as fl
    names = [fl.entry_name(e) for e in entries(fl, project)]
    tags = git(project, "tag", "--list", f"base/{STEM}/*").splitlines()
    return plan_file(project).read_text(encoding="utf-8"), names, tags


def _assert_refused(run: Run, project: Path, target: str, needle: str) -> None:
    """``relink 1 --to target`` exits 1 with a ``problem: at base`` line naming ``needle``.

    The plan JSON, the ledger entries and the base tags stay as they were.
    """
    before = _state(project)
    code, out, err = run("relink", "1", "--to", target)
    assert code == 1, out + err
    lines = prefixed(err, f"problem: at base {target[:7]}: ")
    assert any(needle in line for line in lines), err
    assert _state(project) == before
    assert read_plan(project)["base_commit"] != target


def test_relink_refuses_a_base_missing_an_anchored_file_once_an_item_is_done(run: Run, project: Path) -> None:
    root, _ = _advance_main(project)
    _frozen_plan(run, project, anchor=True, sweep=False)
    _record_done(run, project)
    _assert_refused(run, project, root, "docs/notes.md")


def test_relink_refuses_a_base_missing_an_anchored_file_before_any_item_is_done(run: Run,
                                                                                  project: Path) -> None:
    """A freeze with no item done requires the anchors at the base, so a relink keeps them there too."""
    root, _ = _advance_main(project)
    _frozen_plan(run, project, anchor=True, sweep=False)
    _assert_refused(run, project, root, "docs/notes.md")


def test_relink_refuses_a_base_where_a_sweep_classification_goes_stale(run: Run, project: Path) -> None:
    root, _ = _advance_main(project)
    _frozen_plan(run, project, anchor=False, sweep=True)
    _record_done(run, project)
    _assert_refused(run, project, root, "sweep S1")


def test_relink_accepts_a_rewritten_base_where_the_anchors_and_sweeps_hold(run: Run, project: Path) -> None:
    """The counterpart has the old base's tree, so the anchor on a file the base added and the sweep hold."""
    _, base = _advance_main(project)
    _frozen_plan(run, project, anchor=True, sweep=True)
    assert read_plan(project)["base_commit"] == base
    new = rewrite_base(project, base)
    code, _, err = run("relink", "1")
    assert code == 0, err
    assert read_plan(project)["base_commit"] == new
