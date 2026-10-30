"""Differential guard: the old draft-07 schema, the generated 2020-12 schema and the models judge alike.

The fixtures hold the hand-written schemas as they were before the models became the definition. Every plan
document in the corpus (the fixture plans and one-edit mutations of the full one) must be accepted or
rejected identically by all three, which is what "on-disk plans keep loading" means.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import jsonschema
import pytest
from pydantic import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from harness_lib import plan_models as pm

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plan_models"
_DELETE = object()


def _fixture(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _old_validator() -> jsonschema.protocols.Validator:
    attrs = Resource.from_contents(_fixture("prAttributes.draft07.schema.json"), default_specification=DRAFT7)
    registry = Registry().with_resource("prAttributes.schema.json", attrs)
    return jsonschema.Draft7Validator(_fixture("ActionPlan.draft07.schema.json"), registry=registry)


def _mutated(path: Tuple[Any, ...], value: Any) -> Dict[str, Any]:
    doc = copy.deepcopy(_fixture("0002_Full_ActionPlan.json"))
    node = doc
    for step in path[:-1]:
        node = node[step]
    if value is _DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return doc


MUTATIONS: List[Tuple[Tuple[Any, ...], Any]] = [
    (("plan_id",), "12"), (("plan_id",), 1234), (("plan_id",), "0001\n"), (("plan_id",), _DELETE),
    (("plan_created",), _DELETE), (("plan_created",), 5), (("plan_created",), "TBD"),
    (("execution_model",), _DELETE), (("items",), _DELETE), (("items",), {}), (("items",), []),
    (("base_commit",), "abc"), (("base_commit",), None), (("base_commit",), "G" * 40),
    (("frozen",), None), (("frozen",), {}), (("frozen", "digest"), "xyz"), (("frozen", "date"), "TBD"),
    (("markdown_sync_status",), "other"), (("markdown_sync_status",), None), (("completed",), 5),
    (("branch",), 5), (("context",), "x"), (("context",), None), (("context",), _DELETE),
    (("context", "tags"), "a"), (("context", "deadline"), 5),
    (("context", "owner"), None), (("pr_attributes",), [{"pr": "1"}]),
    (("pr_attributes", 0, "pr"), [1]), (("pr_attributes", 0, "pr"), 1.5), (("pr_attributes", 0, "pr"), None),
    (("pr_attributes", 0, "pr"), 1.0), (("pr_attributes", 0, "pr"), True),
    (("pr_attributes", 0, "review_doc"), "docs/x.json"), (("pr_attributes", 0, "review_doc"), 5),
    (("pr_attributes", 0, "label"), "kept"),
    (("items", 0, "id"), "bad"), (("items", 0, "id"), "AB-1.2.3"), (("items", 0, "status"), "DONE"),
    (("items", 0, "status"), _DELETE), (("items", 0, "evidence"), _DELETE),
    (("items", 0, "model"), "gpt"), (("items", 0, "model"), None), (("items", 0, "priority"), "urgent"),
    (("items", 0, "priority"), None), (("items", 0, "files"), "a"), (("items", 0, "dependencies"), "FX-1"),
    (("items", 0, "dependencies"), None), (("items", 0, "notes"), 5),
    (("items", 0, "anchors"), [{"at": "x", "expect": "y"}]),
    (("items", 0, "anchors"), [{"at": "a.py:1", "expect": ""}]),
    (("items", 0, "anchors", 0, "extra"), 1),
    (("items", 0, "commands", 0, "run"), ""), (("items", 0, "commands", 0, "extra"), 1),
    (("items", 0, "tests", 0, "red"), "ValueError"), (("items", 0, "tests", 0, "node"), "tests/test_a.py"),
    (("items", 0, "x_item_extra"), {"deep": [1]}), (("items", 1, "x_other"), None),
    (("decisions", 0, "options"), [{"id": "only", "summary": "one"}]), (("decisions", 0, "id"), "X1"),
    (("decisions", 0, "chosen"), _DELETE), (("decisions", 0, "extra"), 1),
    (("decisions", 0, "rationale"), None),
    (("values", 0, "assumes"), "x"), (("values", 0, "extra"), 1), (("values", 0, "value"), ""),
    (("formats", 0, "source"), _DELETE), (("sweeps", 0, "id"), "X"), (("sweeps", 0, "hits"), {"a": ""}),
    (("deferred_to_future_plans", 0, "rationale"), _DELETE),
    (("deferred_to_future_plans", 0, "owner"), "kept"), (("x_top_extra",), "kept"),
]


def _corpus() -> List[Tuple[str, Dict[str, Any]]]:
    docs = [(name, _fixture(name)) for name in sorted(p.name for p in FIXTURES.glob("*_ActionPlan.json"))]
    for path, value in MUTATIONS:
        shown = "DELETED" if value is _DELETE else repr(value)
        docs.append((f"{'/'.join(map(str, path))}={shown}", _mutated(path, value)))
    return docs


CORPUS = _corpus()


def _by_models(doc: Dict[str, Any]) -> bool:
    try:
        pm.ActionPlan.model_validate(doc)
    except ValidationError:
        return False
    return True


def test_the_generated_schema_is_a_valid_draft_2020_12_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(pm.schema_dict())
    assert pm.schema_dict()["$schema"] == "https://json-schema.org/draft/2020-12/schema"


@pytest.mark.parametrize("name,doc", CORPUS, ids=[name for name, _ in CORPUS])
def test_old_schema_generated_schema_and_models_agree(name: str, doc: Dict[str, Any]) -> None:
    old = _old_validator().is_valid(doc)
    generated = jsonschema.Draft202012Validator(pm.schema_dict()).is_valid(doc)
    models = _by_models(doc)
    assert (old, generated, models) == (old, old, old), f"old={old} generated={generated} models={models}"


def test_the_corpus_holds_documents_of_both_verdicts() -> None:
    verdicts = {_old_validator().is_valid(doc) for _, doc in CORPUS}
    assert verdicts == {True, False}
    assert all(_old_validator().is_valid(doc) for name, doc in CORPUS if name.endswith("_ActionPlan.json"))
