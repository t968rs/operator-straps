"""Models of an ActionPlan: policy, defaults, the dump policy, error lines and the fixture round trips."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from pydantic import BaseModel, ValidationError

from harness_lib import plan_doc
from harness_lib import plan_models as pm
from harness_lib.plan_enums import ItemStatus, ModelName
from harness_lib.plan_render import render_pip

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plan_models"
EXPECTED: Dict[str, Dict[str, str]] = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
NAMES = sorted(EXPECTED)
OPEN_MODELS = {"ActionPlan", "ActionItem", "Context", "Frozen", "DeferredTopic", "PrAttributes"}
# Old hand-schema object -> model class name.
OLD_OBJECTS = {"action_item": "ActionItem", "anchor": "Anchor", "command": "Command", "test": "PlannedTest",
               "decision": "Decision", "value": "Value", "format": "PlanFormat", "sweep": "Sweep"}


def _raw(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _own_models() -> List[type]:
    return [obj for obj in vars(pm).values()
            if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == pm.__name__]


def _required(model: type) -> set:
    return {name for name, field in model.model_fields.items() if field.is_required()}


# --- model policy -----------------------------------------------------------------------------------------

def test_every_model_allows_or_forbids_extras_and_matches_patterns_like_jsonschema() -> None:
    models = _own_models()
    assert {m.__name__ for m in models if m.model_config["extra"] == "allow"} == OPEN_MODELS
    assert all(m.model_config["extra"] in ("allow", "forbid") for m in models)
    assert all(m.model_config["regex_engine"] == "python-re" for m in models)


def test_a_field_the_old_schema_required_has_no_default() -> None:
    old = json.loads((FIXTURES / "ActionPlan.draft07.schema.json").read_text(encoding="utf-8"))
    attrs = json.loads((FIXTURES / "prAttributes.draft07.schema.json").read_text(encoding="utf-8"))
    wanted = {"ActionPlan": set(old["required"]), "PrAttributes": set(attrs["required"]),
              "Frozen": set(old["properties"]["frozen"]["required"]),
              "DeferredTopic": set(old["properties"]["deferred_to_future_plans"]["items"]["required"])}
    wanted.update({OLD_OBJECTS[name]: set(old["definitions"][name]["required"]) for name in OLD_OBJECTS})
    assert {name: _required(getattr(pm, name)) for name in wanted} == wanted


def test_mutable_fields_are_the_freeze_digest_exclusions() -> None:
    assert set(pm.mutable_top()) == {"completed", "frozen", "markdown_sync_status", "markdown_last_updated"}
    assert set(pm.mutable_item()) == {"status", "evidence", "verification_references"}


def test_a_marker_never_reaches_the_generated_schema() -> None:
    assert "Mutable" not in pm.schema_text()


# --- values -----------------------------------------------------------------------------------------------

def test_absent_optional_fields_read_as_the_old_code_read_a_missing_key() -> None:
    plan = pm.ActionPlan.model_validate(_raw("0001_Minimal_ActionPlan.json"))
    item = plan.items[0]
    assert (plan.base_commit, plan.frozen, plan.completed) == ("", None, None)
    assert (plan.decisions, plan.sweeps) == ([], [])
    assert (item.model, item.files, item.dependencies, item.anchors, item.tests) == (
        ModelName.sonnet, [], None, [], [])
    assert item.status is ItemStatus.PENDING and str(item.status) == "PENDING"


def test_date_fields_stay_strings_whatever_they_hold() -> None:
    plan = pm.ActionPlan.model_validate(_raw("0002_Full_ActionPlan.json"))
    assert plan.plan_created == "2026-10-29T08:30:00"
    assert isinstance(plan.markdown_last_updated, str)


@pytest.mark.parametrize("pr", [12, "draft-1"])
def test_pr_accepts_an_int_or_a_string(pr: Any) -> None:
    assert pm.PrAttributes(pr=pr, branch="b", base_branch="main").pr == pr


@pytest.mark.parametrize("pr", [True, 1.5, [1], None])
def test_pr_rejects_anything_else_with_one_error(pr: Any) -> None:
    with pytest.raises(ValidationError) as caught:
        pm.PrAttributes(pr=pr, branch="b", base_branch="main")
    assert [e["loc"] for e in caught.value.errors()] == [("pr",)]


# --- schema text ------------------------------------------------------------------------------------------

def test_schema_text_declares_the_dialect_and_the_repository_id() -> None:
    text = pm.schema_text()
    schema = json.loads(text)
    assert text.endswith("\n") and schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == ("https://github.com/t968rs/operator-straps/plugins/harness/schemas/"
                             "ActionPlan.schema.json")


def test_the_generated_schema_refers_to_no_sibling_file() -> None:
    refs = [line for line in pm.schema_text().splitlines() if '"$ref"' in line]
    assert refs and all('"#/$defs/' in line for line in refs)


# --- dump policy (plan_doc) -------------------------------------------------------------------------------

@pytest.mark.parametrize("name", NAMES)
def test_load_returns_the_model_and_dumps_the_file_back_unchanged(name: str) -> None:
    plan = plan_doc.load_plan(FIXTURES / name)
    assert isinstance(plan, pm.ActionPlan)
    assert plan_doc.plan_dict(plan) == _raw(name)


@pytest.mark.parametrize("name", NAMES)
def test_a_loaded_fixture_keeps_the_freeze_digest_the_old_code_computed(name: str) -> None:
    assert plan_doc.frozen_digest(plan_doc.load_plan(FIXTURES / name)) == EXPECTED[name]["digest"]


def test_the_digest_ignores_execution_fields_and_sees_every_other_field() -> None:
    plan = plan_doc.load_plan(FIXTURES / "0002_Full_ActionPlan.json")
    before = plan_doc.frozen_digest(plan)
    plan.items[0].status, plan.items[0].evidence, plan.completed = ItemStatus.BLOCKED, "x", "2026-11-01"
    assert plan_doc.frozen_digest(plan) == before
    plan.items[0].title = "changed"
    assert plan_doc.frozen_digest(plan) != before


def test_an_in_place_append_to_a_list_that_was_never_set_is_written() -> None:
    plan = plan_doc.load_plan(FIXTURES / "0001_Minimal_ActionPlan.json")
    plan.items[0].anchors.append(pm.Anchor(at="src/a.py:1", expect="x"))
    assert plan_doc.plan_dict(plan)["items"][0]["anchors"] == [{"at": "src/a.py:1", "expect": "x"}]


def test_a_field_left_at_its_default_is_not_written() -> None:
    plan = plan_doc.load_plan(FIXTURES / "0001_Minimal_ActionPlan.json")
    assert set(plan_doc.plan_dict(plan)["items"][0]) == {"id", "title", "action", "status", "evidence"}


def test_reopening_removes_completed_from_the_file() -> None:
    plan = plan_doc.load_plan(FIXTURES / "0001_Minimal_ActionPlan.json")
    plan.completed = "2026-11-01"
    assert plan_doc.plan_dict(plan)["completed"] == "2026-11-01"
    plan.completed = None
    plan.model_fields_set.discard("completed")
    assert "completed" not in plan_doc.plan_dict(plan)


def test_dumping_does_not_mark_the_plan_it_was_given() -> None:
    plan = plan_doc.load_plan(FIXTURES / "0001_Minimal_ActionPlan.json")
    plan.items[0].anchors.append(pm.Anchor(at="src/a.py:1", expect="x"))
    plan_doc.plan_dict(plan)
    assert "anchors" not in plan.items[0].model_fields_set


@pytest.mark.parametrize("name", NAMES)
def test_the_pip_of_a_loaded_fixture_is_the_one_the_old_renderer_wrote(name: str) -> None:
    golden = (FIXTURES / EXPECTED[name]["pip"]).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert render_pip(plan_doc.load_plan(FIXTURES / name), name) == golden


# --- error lines ------------------------------------------------------------------------------------------

def test_schema_problems_name_the_json_path_and_print_a_defect_once() -> None:
    raw = _raw("0002_Full_ActionPlan.json")
    raw["pr_attributes"][0]["pr"] = [1]
    raw["items"][0]["tests"][0]["red"] = "ValueError"
    problems = plan_doc.schema_problems(raw)
    assert [p.split(":")[1].strip() for p in problems] == ["items/0/tests/0/red", "pr_attributes/0/pr"]
    assert all(p.startswith("schema: ") for p in problems)


def test_schema_problems_of_a_valid_plan_are_empty() -> None:
    assert plan_doc.schema_problems(_raw("0002_Full_ActionPlan.json")) == []


def test_a_long_message_is_cut_at_two_hundred_characters() -> None:
    raw = _raw("0001_Minimal_ActionPlan.json")
    raw["items"][0]["status"] = "x" * 500
    (line,) = plan_doc.schema_problems(raw)
    assert len(line.split(": ", 2)[2]) <= 200


def test_an_invalid_file_raises_a_plan_error_holding_the_schema_lines(tmp_path: Path) -> None:
    raw = _raw("0001_Minimal_ActionPlan.json")
    del raw["items"][0]["evidence"]
    path = tmp_path / "0001_Bad_ActionPlan.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(plan_doc.PlanError) as caught:
        plan_doc.load_plan(path)
    assert caught.value.problems == ["schema: items/0/evidence: Field required"]


@pytest.mark.parametrize("text,fragment", [("{", "is not JSON"), ("[1]", "does not hold a JSON object")])
def test_parse_plan_reports_text_that_is_not_a_plan_object(text: str, fragment: str) -> None:
    with pytest.raises(plan_doc.PlanError) as caught:
        plan_doc.parse_plan(text, "x_ActionPlan.json")
    assert fragment in caught.value.problems[0]


def test_the_digest_exclusions_of_plan_doc_come_from_the_models() -> None:
    assert plan_doc.MUTABLE_TOP == pm.mutable_top() and plan_doc.MUTABLE_ITEM == pm.mutable_item()
