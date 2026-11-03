"""``plan_api``, the heredoc authoring path: ``load`` returns the model; ``write`` validates and saves."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable, Dict

import pytest

from harness_lib import plan_api
from harness_lib import plan_models as pm
from harness_lib.plan_doc import PlanError
from harness_lib.plan_enums import ItemStatus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plan_models"
PLANS = "docs/PLANS"
MINIMAL, INFLIGHT = "0001_Minimal_ActionPlan.json", "0003_Inflight_ActionPlan.json"
FULL = "0002_Full_ActionPlan.json"


@pytest.fixture()
def project(make_project) -> Path:
    root = make_project()
    (root / PLANS).mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture()
def put(project: Path) -> Callable[[str], Path]:
    """Copy a fixture plan into the project's plans folder, with its PIP beside it; return the plan file."""
    def _put(name: str) -> Path:
        target = project / PLANS / name
        shutil.copyfile(FIXTURES / name, target)
        pip = name.replace("_ActionPlan.json", "_PIP.md")
        shutil.copyfile(FIXTURES / pip, project / PLANS / pip)
        return target
    return _put


def _bytes(path: Path) -> Dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(path.parent.glob("*"))}


def _item(**extra: Any) -> pm.ActionItem:
    fields: Dict[str, Any] = {"id": "MN-2", "title": "Second", "action": "Do it.",
                              "status": ItemStatus.PENDING, "evidence": "not started"}
    fields.update(extra)
    return pm.ActionItem(**fields)


def _refused(project: Path, plan: pm.ActionPlan) -> PlanError:
    with pytest.raises(PlanError) as caught:
        plan_api.write(plan, repo=project)
    return caught.value


# --- load -------------------------------------------------------------------------------------------------

def test_load_finds_a_plan_by_id_padded_or_not_and_by_path(project: Path, put) -> None:
    path = put(MINIMAL)
    by_id, bare, by_path = (plan_api.load(ref, repo=project) for ref in ("0001", "1", str(path)))
    assert isinstance(by_id, pm.ActionPlan) and by_id == bare == by_path


def test_load_refuses_a_plan_that_does_not_validate(project: Path, put) -> None:
    path = put(MINIMAL)
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["items"][0]["evidence"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(PlanError) as caught:
        plan_api.load("0001", repo=project)
    assert caught.value.problems == ["schema: items/0/evidence: Field required"]


def test_load_names_an_unknown_plan(project: Path) -> None:
    with pytest.raises(PlanError) as caught:
        plan_api.load("0042", repo=project)
    assert "no plan 0042" in caught.value.problems[0]


# --- write ------------------------------------------------------------------------------------------------

def test_write_saves_the_json_and_the_pip_and_returns_the_validated_plan(project: Path, put) -> None:
    path = put(MINIMAL)
    plan = plan_api.load("0001", repo=project)
    revised = plan.model_copy(update={"items": [*plan.items, _item()]}, deep=True)
    written = plan_api.write(revised, repo=project)
    assert isinstance(written, pm.ActionPlan) and [i.id for i in written.items] == ["MN-1", "MN-2"]
    assert [i["id"] for i in json.loads(path.read_text(encoding="utf-8"))["items"]] == ["MN-1", "MN-2"]
    assert "### MN-2: Second" in (path.parent / "0001_Minimal_PIP.md").read_text(encoding="utf-8")
    assert [i.id for i in plan_api.load("0001", repo=project).items] == ["MN-1", "MN-2"]


def test_write_keeps_the_extra_keys_the_file_already_carries(project: Path, put) -> None:
    path = put(FULL)
    plan = plan_api.load("0002", repo=project)
    plan_api.write(plan.model_copy(update={"execution_model": "serial"}, deep=True), repo=project)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["x_top_extra"] == {"k": [1, 2, None]} and raw["items"][0]["x_item_extra"] == 3


def test_write_saves_an_in_place_append_to_a_list_never_set(project: Path, put) -> None:
    path = put(MINIMAL)
    plan = plan_api.load("0001", repo=project)
    plan.items[0].anchors.append(pm.Anchor(at="src/a.py:1", expect="x"))
    plan_api.write(plan, repo=project)
    assert json.loads(path.read_text(encoding="utf-8"))["items"][0]["anchors"] == [
        {"at": "src/a.py:1", "expect": "x"}]


def test_write_refuses_an_invalid_plan_with_full_paths_and_writes_nothing(project: Path, put) -> None:
    path = put(MINIMAL)
    before = _bytes(path)
    plan = plan_api.load("0001", repo=project)
    broken = plan.model_copy(update={"items": [*plan.items, {"id": "bad", "status": "DONE"}]}, deep=True)
    problems = _refused(project, broken).problems
    assert any(p.startswith("schema: items/1/id") for p in problems)
    assert any(p.startswith("schema: items/1/status") for p in problems)
    assert _bytes(path) == before


def test_write_refuses_a_duplicate_item_id(project: Path, put) -> None:
    path = put(MINIMAL)
    before = _bytes(path)
    plan = plan_api.load("0001", repo=project)
    twice = plan.model_copy(update={"items": [*plan.items, _item(id="MN-1")]}, deep=True)
    assert "item id MN-1 is used 2 times" in _refused(project, twice).problems
    assert _bytes(path) == before


def test_write_refuses_a_plan_id_with_no_file(project: Path, put) -> None:
    path = put(MINIMAL)
    before = _bytes(path)
    moved = plan_api.load("0001", repo=project).model_copy(update={"plan_id": "0009"}, deep=True)
    assert "no plan 0009" in _refused(project, moved).problems[0]
    assert _bytes(path) == before


def test_write_refuses_to_change_the_base_commit_or_the_freeze_record(project: Path, put) -> None:
    path = put(INFLIGHT)
    before = _bytes(path)
    plan = plan_api.load("0003", repo=project)
    problems = _refused(project, plan.model_copy(update={"base_commit": "b" * 40}, deep=True)).problems
    assert any("base_commit" in p for p in problems)
    unfrozen = plan.model_copy(update={"frozen": None}, deep=True)
    assert any("frozen" in p for p in _refused(project, unfrozen).problems)
    assert _bytes(path) == before


def test_write_refuses_a_copy_loaded_before_the_file_changed(project: Path, put) -> None:
    path = put(MINIMAL)
    stale = plan_api.load("0001", repo=project)
    fresh = plan_api.load("0001", repo=project)
    plan_api.write(fresh.model_copy(update={"items": [*fresh.items, _item()]}, deep=True), repo=project)
    before = _bytes(path)
    assert "changed on disk since it was loaded" in _refused(project, stale).problems[0]
    assert _bytes(path) == before


def test_write_refuses_a_plan_that_was_not_loaded(project: Path, put) -> None:
    put(MINIMAL)
    built = pm.ActionPlan.model_validate(json.loads((FIXTURES / MINIMAL).read_text(encoding="utf-8")))
    assert "not loaded with plan_api.load" in _refused(project, built).problems[0]


def test_write_refuses_a_misspelled_field_on_the_plan_or_an_item(project: Path, put) -> None:
    path = put(MINIMAL)
    before = _bytes(path)
    plan = plan_api.load("0001", repo=project)
    item = plan.items[0].model_copy(update={"modle": "opus"})
    typo = plan.model_copy(update={"items": [item], "execution_modle": "serial"}, deep=True)
    problems = " | ".join(_refused(project, typo).problems)
    assert "modle" in problems and "execution_modle" in problems
    assert _bytes(path) == before


def test_write_on_a_frozen_plan_refuses_execution_fields_and_saves_a_design_edit(project: Path, put) -> None:
    path = put(INFLIGHT)
    before = _bytes(path)
    plan = plan_api.load("0003", repo=project)
    moved = plan.model_copy(deep=True)
    moved.items[0].status, moved.items[1].evidence = ItemStatus.PENDING, "unblocked by hand"
    problems = " | ".join(_refused(project, moved).problems)
    assert "IN-1 status" in problems and "IN-2 evidence" in problems and "only plan.py record" in problems
    assert _bytes(path) == before
    retitled = plan.model_copy(deep=True)
    retitled.items[1].title = "Renamed while frozen"
    written = plan_api.write(retitled, repo=project)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["items"][1]["title"] == "Renamed while frozen"
    assert raw["frozen"]["commit"] == written.frozen.commit
