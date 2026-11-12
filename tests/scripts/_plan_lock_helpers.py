"""Shared helpers of the plan lock tests (``test_plan_lock.py``, ``test_plan_relink_lock.py``).

Each helper drives ``plan.py`` through the ``run`` fixture of ``_plan_driver_helpers`` or reads the
freeze ledger and tags of plan 0001 in a ``make_project`` repo.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from conftest import git

from _plan_driver_helpers import PLANS, SUB_TEST, Run, plan_file, read_plan, write_plan

STEM = "plan/0001-add-operators"
PLANNED = f"{PLANS}/0001/tests/tests/test_calc_sub.py"


def _item() -> Dict[str, Any]:
    return {"id": "TASK-1", "title": "Add sub", "action": "Add sub beside add.", "status": "PENDING",
            "evidence": "not started", "files": ["src/calc.py", "tests/test_calc_sub.py"],
            "anchors": [{"at": "src/calc.py:1", "expect": "def add(a, b):"}],
            "tests": [{"node": "tests/test_calc_sub.py::test_sub", "red": "ImportError"}]}


def commit_all(project: Path, message: str) -> str:
    """Stage every change, commit it and return the new HEAD."""
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", message)
    return git(project, "rev-parse", "HEAD")


def fill(run: Run, project: Path, freeze: bool = True) -> str:
    """``new`` and the planned test, committed as the skeleton; then TASK-1, and a freeze unless told not to.

    The committed skeleton makes the plan JSON and the planned test tracked, so the frozen plan JSON differs
    from HEAD until it is committed. Returns the freeze's stdout, or '' without a freeze.
    """
    code, _, err = run("new", "Add operators", "--spec", "docs/spec.md")
    assert code == 0, err
    planned = project / PLANNED
    planned.parent.mkdir(parents=True, exist_ok=True)
    planned.write_text(SUB_TEST, encoding="utf-8")
    commit_all(project, "plan 0001 skeleton")
    plan = read_plan(project)
    plan["items"] = [_item()]
    write_plan(project, plan)
    if not freeze:
        return ""
    code, out, err = run("freeze", "1")
    assert code == 0, err
    return out


def kind_of(entry: Any) -> str:
    return getattr(entry.kind, "value", entry.kind)


def ledger_folder(fl: Any, project: Path) -> Path:
    return fl.ledger_dir(project / PLANS, STEM)


def entries(fl: Any, project: Path) -> List[Any]:
    return list(fl.load_entries(ledger_folder(fl, project)))


def tag_target(project: Path, name: str) -> str:
    """The object the tag ``name`` peels to, or '' when no such tag exists."""
    if git(project, "tag", "--list", name) != name:
        return ""
    return git(project, "rev-parse", f"refs/tags/{name}^{{}}")


def plan_rel(project: Path) -> str:
    return plan_file(project).relative_to(project).as_posix()


def prefixed(text: str, prefix: str) -> List[str]:
    return [line for line in text.splitlines() if line.startswith(prefix)]


def advance_main(project: Path) -> str:
    """Commit a note on ``main`` and fast-forward ``feat-x`` to it, so the base commit is not the root."""
    git(project, "checkout", "-q", "main")
    (project / "docs" / "notes.md").write_text("notes\n", encoding="utf-8")
    base = commit_all(project, "notes")
    git(project, "checkout", "-q", "feat-x")
    git(project, "merge", "-q", "--ff-only", "main")
    return base


def rewrite_base(project: Path, old: str) -> str:
    """Replace ``old`` by a commit with its tree and parent under another message, and replay ``feat-x``
    on it, as a rebase does; returns the replacement, which has ``old``'s patch-id."""
    new = git(project, "commit-tree", f"{old}^{{tree}}", "-p", f"{old}^", "-m", "notes, reworded")
    git(project, "rebase", "-q", "--onto", new, old, "feat-x")
    return new
