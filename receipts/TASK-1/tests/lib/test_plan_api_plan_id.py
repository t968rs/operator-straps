"""``plan_api.write`` names a changed ``plan_id`` instead of calling the target plan stale."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from harness_lib import plan_api
from harness_lib.plan_doc import PlanError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plan_models"
PLANS = "docs/PLANS"
NAMES = ("0001_Minimal_ActionPlan.json", "0003_Inflight_ActionPlan.json")


@pytest.fixture()
def project(make_project) -> Path:
    root = make_project()
    (root / PLANS).mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        shutil.copyfile(FIXTURES / name, root / PLANS / name)
        pip = name.replace("_ActionPlan.json", "_PIP.md")
        shutil.copyfile(FIXTURES / pip, root / PLANS / pip)
    return root


def test_write_refuses_a_plan_id_retargeted_to_another_plan(project: Path) -> None:
    moved = plan_api.load("0001", repo=project).model_copy(deep=True)
    moved.plan_id = "0003"
    before = (project / PLANS / NAMES[1]).read_bytes()
    with pytest.raises(PlanError) as caught:
        plan_api.write(moved, repo=project)
    assert any("plan_id differs from the loaded plan 0001" in line for line in caught.value.problems)
    assert not any("changed on disk" in line for line in caught.value.problems)
    assert (project / PLANS / NAMES[1]).read_bytes() == before
