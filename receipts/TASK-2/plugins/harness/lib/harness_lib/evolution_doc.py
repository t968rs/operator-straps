"""Where a plan's DesignEvolution catalog lives, how it loads and saves, and its check against the plan.

The catalog is ``<plans>/<id>/DesignEvolution.json``. A missing file loads as None; a file that does not
validate is a ``PlanError`` of ``schema:`` lines; ``plan_problems`` names a catalog of another plan and each
change item the plan does not have.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pydantic import ValidationError

from harness_lib import plan_doc
from harness_lib.evolution_models import DesignEvolution
from harness_lib.plan_doc import PlanError
from harness_lib.plan_models import ActionPlan

CATALOG_NAME = "DesignEvolution.json"


def catalog_path(plans_dir: Path, plan_id: str) -> Path:
    """``<plans_dir>/<plan_id>/DesignEvolution.json``."""
    return plans_dir / plan_id / CATALOG_NAME


def _parse(text: str, name: str) -> DesignEvolution:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise PlanError([f"{name} is not JSON: {exc}"]) from exc
    if not isinstance(data, dict):
        raise PlanError([f"{name} does not hold a JSON object"])
    try:
        return DesignEvolution.model_validate(data)
    except ValidationError as exc:
        raise PlanError(plan_doc.schema_lines(exc)) from exc


def load_evolution(path: Path) -> Optional[DesignEvolution]:
    """The catalog at ``path``; None when the file is absent, a ``PlanError`` when it is invalid."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PlanError([f"cannot read {path.as_posix()}: {exc}"]) from exc
    return _parse(text, path.name)


def dump_evolution(evo: DesignEvolution) -> str:
    """The JSON text of a catalog; absent optional fields are left out."""
    body = evo.model_dump(mode="json", exclude_none=True)
    return json.dumps(body, indent=2, ensure_ascii=False) + "\n"


def save_evolution(path: Path, evo: DesignEvolution) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_evolution(evo), encoding="utf-8")


def plan_problems(evo: DesignEvolution, plan: ActionPlan) -> List[str]:
    """A catalog of another plan, and each change item that is no item of ``plan``."""
    problems: List[str] = []
    if evo.plan_id != plan.plan_id:
        problems.append(f"catalog is for plan {evo.plan_id}, not plan {plan.plan_id}")
    known = {item.id for item in plan.items}
    for change in evo.changes:
        problems.extend(f"change {change.id} names item {item}, which plan {plan.plan_id} does not have"
                        for item in change.items if item not in known)
    return problems
