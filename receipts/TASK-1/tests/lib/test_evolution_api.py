"""``evolution_api``: the agent's write path into a plan's ``DesignEvolution.json``.

``add`` validates one ``DesignChange`` against the catalog (unique id) and the plan (known items), creates
the catalog from the plan on first use, writes it and rebuilds the plan's ``live.js``. ``write`` validates a
whole catalog. Neither touches the plan file or its PIP.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from harness_lib import evolution_api
from harness_lib.evolution_models import DesignChange, DesignEvolution
from harness_lib.plan_doc import PlanError

WALK_ROOTS = ()  # walks only the plans folder of a make_project repo
PLANS = "docs/PLANS"
PLAN_NAME = "0001_Add_operators_ActionPlan.json"
PLAN = {
    "plan_id": "0001", "plan_created": "2026-11-10", "execution_model": "serial", "source_document": "docs/spec.md",
    "branch": "feat-x", "base_branch": "main", "base_commit": "e" * 40,
    "items": [{"id": "TASK-1", "title": "Add sub", "action": "Add sub.", "status": "PENDING",
               "evidence": "not started", "files": ["src/calc.py"]}],
}


def change(ident: str = "EX1", **over: Any) -> DesignChange:
    raw: Dict[str, Any] = {
        "id": ident, "discovered_by": "implementer", "phase": "post-exec-start", "items": ["TASK-1"],
        "original": {"doc": "plan", "location": "TASK-1 files", "indicated": "src/calc.py only"},
        "issue": {"category": "spec-coverage", "why_categorical": "x", "why_free_form": "y"},
        "new_outcome": {"doc": "plan", "indicated": "also src/helper.py"},
        "why_new_outcome": {"category": "execution-blocker", "free_form": "z"},
    }
    raw.update(over)
    return DesignChange.model_validate(raw)


@pytest.fixture()
def project(make_project) -> Path:
    root = make_project(files={"docs/spec.md": "# Spec\n"})
    (root / PLANS).mkdir(parents=True, exist_ok=True)
    (root / PLANS / PLAN_NAME).write_text(json.dumps(PLAN, indent=2), encoding="utf-8")
    return root


def catalog_file(project: Path) -> Path:
    return project / PLANS / "0001" / "DesignEvolution.json"


def test_the_first_add_creates_the_catalog_from_the_plan(project: Path) -> None:
    evo = evolution_api.add("1", change(), repo=project)
    assert isinstance(evo, DesignEvolution) and catalog_file(project).is_file()
    assert evo.plan_id == "0001" and evo.branch_lineage == "main-->feat-x"
    assert evo.primary_documents == {"plan": f"{PLANS}/{PLAN_NAME}", "spec": "docs/spec.md"}
    assert [c.id for c in evo.changes] == ["EX1"] and evo.changes[0].date


def test_add_appends_and_load_reads_back(project: Path) -> None:
    evolution_api.add("1", change("EX1"), repo=project)
    evolution_api.add("0001", change("EX2"), repo=project)
    assert [c.id for c in evolution_api.load("1", repo=project).changes] == ["EX1", "EX2"]


def test_load_without_a_catalog_returns_a_fresh_one_and_writes_nothing(project: Path) -> None:
    evo = evolution_api.load("1", repo=project)
    assert evo.changes == [] and evo.plan_id == "0001" and not catalog_file(project).exists()


def test_add_refuses_a_duplicate_id(project: Path) -> None:
    evolution_api.add("1", change("EX1"), repo=project)
    with pytest.raises(PlanError) as caught:
        evolution_api.add("1", change("EX1"), repo=project)
    assert any("EX1" in p for p in caught.value.problems)


def test_add_refuses_an_unknown_item_and_writes_nothing(project: Path) -> None:
    with pytest.raises(PlanError) as caught:
        evolution_api.add("1", change(items=["TASK-9"]), repo=project)
    assert any("TASK-9" in p for p in caught.value.problems)
    assert not catalog_file(project).exists()


def test_add_rebuilds_live_js(project: Path) -> None:
    evolution_api.add("1", change(), repo=project)
    live = (project / PLANS / "0001" / "live.js").read_text(encoding="utf-8")
    assert live.startswith("window.PLAN_LIVE = ") and '"EX1"' in live


def test_add_leaves_the_plan_file_alone(project: Path) -> None:
    before = (project / PLANS / PLAN_NAME).read_bytes()
    evolution_api.add("1", change(), repo=project)
    assert (project / PLANS / PLAN_NAME).read_bytes() == before
    assert not list((project / PLANS).glob("0001_*_PIP.*"))


def test_write_validates_the_whole_catalog(project: Path) -> None:
    evo = evolution_api.add("1", change(), repo=project)
    bad = evo.model_copy(update={"changes": [*evo.changes, change("EX2", items=["TASK-7"])]}, deep=True)
    with pytest.raises(PlanError) as caught:
        evolution_api.write(bad, repo=project)
    assert any("TASK-7" in p for p in caught.value.problems)


def test_an_unknown_plan_is_refused(project: Path) -> None:
    with pytest.raises(PlanError):
        evolution_api.add("7", change(), repo=project)


def test_next_id_returns_the_next_free_number_and_writes_nothing(project: Path) -> None:
    assert evolution_api.next_id("1", repo=project) == "EX1" and not catalog_file(project).exists()
    evolution_api.add("1", change("EX1"), repo=project)
    evolution_api.add("1", change("EX4"), repo=project)
    assert evolution_api.next_id("1", repo=project) == "EX5"
    assert evolution_api.next_id("1", prefix="CX", repo=project) == "CX1"
