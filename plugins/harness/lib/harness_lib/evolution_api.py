"""Authoring API for a plan's ``DesignEvolution.json``, called from a heredoc: ``add`` a change, or ``load``,
change a copy and ``write`` it.

Every function is a driver entry point: it activates the project named by ``repo`` (default: the working
directory) itself, since a heredoc has no driver to do it, and resolves ``plan`` the way ``plan_api`` does (a
plan id padded or not, or a plan file). ``load`` returns the plan's catalog, or a fresh one built from the plan
(nothing is written). ``next_id`` names the next free change id of a prefix. ``add`` refuses (every problem at
once, nothing written) a duplicate change id and a change item the plan does not have; ``write`` validates a
whole catalog the same way. Each save rebuilds the plan's ``live.js``; the plan file and its PIP stay as they
are. Without pydantic at the floor ``doctor.REQUIRED_MODULES`` names, the import prints one ``problem:`` line
and exits 1.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List

from harness_lib.doctor import missing_pydantic

_MISSING = missing_pydantic()
if _MISSING is not None:
    print(f"problem: {_MISSING} is not installed; evolution_api needs it (pip install '{_MISSING}')",
          file=sys.stderr)
    sys.exit(1)

from pydantic import ValidationError  # noqa: E402

from harness_lib import evolution_doc as ed  # noqa: E402
from harness_lib import plan_doc as pd  # noqa: E402
from harness_lib import plan_live  # noqa: E402
from harness_lib.config import active  # noqa: E402
from harness_lib.evolution_models import DesignChange, DesignEvolution  # noqa: E402
from harness_lib.plan_api import PlanRef, Repo, _activate, _plan_file  # noqa: E402
from harness_lib.plan_models import ActionPlan  # noqa: E402

_TITLE = re.compile(r"^\d{4}_(?P<title>.+)" + re.escape(pd.PLAN_SUFFIX) + "$")


def _relative(path: Path) -> str:
    """``path`` as a posix path under the project root, else as given."""
    try:
        return path.resolve().relative_to(active().project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _feature(plan_file: Path) -> str:
    """The title part of the plan file name, underscores read as spaces."""
    found = _TITLE.match(plan_file.name)
    return (found.group("title") if found else plan_file.name).replace("_", " ")


def _fresh(plan: ActionPlan, plan_file: Path) -> DesignEvolution:
    docs = {"plan": _relative(plan_file)}
    if plan.source_document:
        docs["spec"] = plan.source_document
    lineage = f"{plan.base_branch or 'none'}-->{plan.branch or 'none'}"
    return DesignEvolution(plan_id=plan.plan_id, feature=_feature(plan_file), branch_lineage=lineage,
                           primary_documents=docs)


def _load(plan: ActionPlan, plan_file: Path) -> DesignEvolution:
    saved = ed.load_evolution(ed.catalog_path(plan_file.parent, plan.plan_id))
    return saved if saved is not None else _fresh(plan, plan_file)


def _problems(evo: DesignEvolution, plan: ActionPlan) -> List[str]:
    """Model-rule problems of the whole catalog (a copy skips validation) and its problems against ``plan``."""
    problems: List[str] = []
    try:
        DesignEvolution.model_validate(evo.model_dump(mode="json"))
    except ValidationError as exc:
        problems += pd.schema_lines(exc)
    return problems + ed.plan_problems(evo, plan)


def _save(evo: DesignEvolution, plan: ActionPlan, plan_file: Path) -> DesignEvolution:
    """Refuse a catalog with problems; else save it, rebuild ``live.js`` and return it."""
    problems = _problems(evo, plan)
    if problems:
        raise pd.PlanError(problems)
    ed.save_evolution(ed.catalog_path(plan_file.parent, plan.plan_id), evo)
    plan_live.write_live(plan_file.parent, plan.plan_id)
    return evo


def load(plan: PlanRef, repo: Repo = None) -> DesignEvolution:
    """The catalog of plan ``plan``; a fresh one built from the plan, not saved, when none exists."""
    _activate(repo)
    plan_file = _plan_file(plan)
    return _load(pd.load_plan(plan_file), plan_file)


def next_id(plan: PlanRef, prefix: str = "EX", repo: Repo = None) -> str:
    """``prefix`` plus one more than the highest number any change id of that prefix uses; nothing is saved."""
    used = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    numbers = [int(m.group(1)) for c in load(plan, repo).changes if (m := used.match(c.id))]
    return f"{prefix}{max(numbers, default=0) + 1}"


def add(plan: PlanRef, change: DesignChange, repo: Repo = None) -> DesignEvolution:
    """Append ``change`` to the catalog (created on first use) and save it; else refuse with every problem."""
    _activate(repo)
    plan_file = _plan_file(plan)
    plan_doc = pd.load_plan(plan_file)
    evo = _load(plan_doc, plan_file)
    if evo.find(change.id) is not None:
        raise pd.PlanError([f"change {change.id} is already in the catalog of plan {plan_doc.plan_id}"])
    grown = evo.model_copy(update={"changes": [*evo.changes, change]}, deep=True)
    return _save(grown, plan_doc, plan_file)


def write(evolution: DesignEvolution, repo: Repo = None) -> DesignEvolution:
    """Validate the whole catalog against its plan, save it and rebuild ``live.js``; else refuse."""
    _activate(repo)
    plan_file = pd.find_plan(active().path(active().artifacts.plans), evolution.plan_id)
    return _save(evolution, pd.load_plan(plan_file), plan_file)
