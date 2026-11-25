"""``evolution_doc``: where a plan's DesignEvolution lives, how it loads and saves, and its check against the plan.

The catalog is ``<plans>/<id>/DesignEvolution.json``. A missing file loads as None; a file that does not
validate is a ``PlanError`` of ``schema:`` lines; ``plan_problems`` names a catalog of another plan and each
change item the plan does not have.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from harness_lib import evolution_doc as ed
from harness_lib.evolution_models import DesignEvolution
from harness_lib.plan_doc import PlanError
from harness_lib.plan_models import ActionPlan

WALK_ROOTS = ()  # walks only tmp_path


def plan() -> ActionPlan:
    item: Dict[str, Any] = {"id": "TASK-1", "title": "Add sub", "action": "Add sub.", "status": "PENDING",
                            "evidence": "not started", "files": ["src/calc.py"]}
    return ActionPlan.model_validate({"plan_id": "0001", "plan_created": "2026-11-10",
                                      "execution_model": "serial", "items": [item]})


def evolution(items: List[str]) -> DesignEvolution:
    return DesignEvolution.model_validate({
        "plan_id": "0001", "feature": "Add operators", "branch_lineage": "main-->feat-x",
        "primary_documents": {"plan": "docs/PLANS/0001_Add_operators_ActionPlan.json"},
        "changes": [{"id": "EX1", "discovered_by": "implementer", "phase": "post-exec-start", "items": items,
                     "original": {"doc": "plan", "location": "TASK-1", "indicated": "src/calc.py"},
                     "issue": {"category": "spec-coverage", "why_categorical": "x", "why_free_form": "y"},
                     "new_outcome": {"doc": "plan", "indicated": "also src/helper.py"},
                     "why_new_outcome": {"category": "execution-blocker", "free_form": "z"},
                     "date": "2026-11-10"}]})


def test_the_catalog_lives_in_the_plan_folder_and_round_trips(tmp_path: Path) -> None:
    path = ed.catalog_path(tmp_path, "0001")
    assert path == tmp_path / "0001" / "DesignEvolution.json"
    assert ed.load_evolution(path) is None
    ed.save_evolution(path, evolution(["TASK-1"]))
    assert ed.load_evolution(path) == evolution(["TASK-1"])


def test_a_catalog_that_does_not_validate_is_a_schema_problem(tmp_path: Path) -> None:
    path = ed.catalog_path(tmp_path, "0001")
    path.parent.mkdir(parents=True)
    path.write_text('{"plan_id": "0001"}', encoding="utf-8")
    with pytest.raises(PlanError) as caught:
        ed.load_evolution(path)
    assert all(p.startswith("schema: ") for p in caught.value.problems)


def test_a_catalog_names_only_items_of_its_plan() -> None:
    problems = ed.plan_problems(evolution(["TASK-1", "TASK-9"]), plan())
    assert len(problems) == 1 and "TASK-9" in problems[0] and "EX1" in problems[0]


def test_a_catalog_of_another_plan_is_a_problem() -> None:
    other = evolution(["TASK-1"]).model_copy(update={"plan_id": "0002"})
    assert any("0002" in p for p in ed.plan_problems(other, plan()))
