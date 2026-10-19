"""The TODO sync schemas: ``catalogs/TodoCatalog.schema.json`` (the catalog shape rule T1 falls back to) and
``TodoSyncReport.schema.json`` (the report the todo-watch mod reads) accept their fixtures, reject known-bad
records, and are documented in the schemas README.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict

import jsonschema
import pytest

from conftest import FIXTURES, PLUGIN_ROOT

SCHEMAS = PLUGIN_ROOT / "schemas"
CATALOG_SCHEMA = SCHEMAS / "catalogs" / "TodoCatalog.schema.json"
REPORT_SCHEMA = SCHEMAS / "TodoSyncReport.schema.json"
MIN_CATALOG = FIXTURES / "todo_sync" / "TodoCatalog.min.json"

REPORT: Dict[str, Any] = {
    "schema_version": 1, "generated_at": "2026-10-19T16:00:00Z", "elapsed_ms": 412.5,
    "rules_run": ["S1", "P1", "T1"], "rules_skipped": [{"rule": "G1", "reason": "no issue cache"}],
    "drift": 1, "by_rule": {"P1": 1}, "counts": {"error": 1, "warn": 1}, "gh_fetched_at": None,
    "findings": [
        {"rule": "P1", "severity": "error", "counted": True, "file": "docs/PLANS/0001_X_PIP.md", "line": 12,
         "subject": "ABC-1", "message": "COMPLETE item has 1 unchecked box", "fix": "Check the box."},
        {"rule": "S6", "severity": "warn", "counted": False, "file": "docs/RESEARCH/Old",
         "message": "uncovered"},
    ],
}


def _validator(path: Path) -> jsonschema.protocols.Validator:
    schema = json.loads(path.read_text(encoding="utf-8"))
    cls = jsonschema.validators.validator_for(schema)
    return cls(schema, format_checker=jsonschema.FormatChecker())


def _errors(path: Path, doc: Any) -> list:
    return [e.message for e in _validator(path).iter_errors(doc)]


@pytest.fixture()
def catalog() -> Dict[str, Any]:
    return json.loads(MIN_CATALOG.read_text(encoding="utf-8"))


def test_min_catalog_fixture_validates(catalog: Dict[str, Any]) -> None:
    assert _errors(CATALOG_SCHEMA, catalog) == []


def test_catalog_schema_is_draft_2020_12() -> None:
    schema = json.loads(CATALOG_SCHEMA.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "definitions" not in schema and "item" in schema["$defs"]


@pytest.mark.parametrize("mutate", [
    lambda d: d["items"][0].update(id="TODO-1"),
    lambda d: d["items"][0].update(status="COMPLETE"),
    lambda d: d["items"][0].update(notes="free text"),
    lambda d: d["items"][2].update(decision_question=None),
    lambda d: d["items"][1]["sources"][0].update(ref="/abs/_IMPL_TODO.md"),
    lambda d: d["items"][1]["sources"][0].update(ref="docs\\plans\\_IMPL_TODO.md"),
    lambda d: d["close_candidates"][0].update(current_state="OPEN"),
    lambda d: d.pop("trackers"),
], ids=["id-pattern", "terminal-status", "unknown-item-key", "decision-question", "abs-stub-ref",
        "backslash-stub-ref", "close-state", "trackers-required"])
def test_catalog_schema_rejects(catalog: Dict[str, Any], mutate) -> None:
    bad = copy.deepcopy(catalog)
    mutate(bad)
    assert _errors(CATALOG_SCHEMA, bad)


def test_report_fixture_validates() -> None:
    assert _errors(REPORT_SCHEMA, REPORT) == []


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema_version=2),
    lambda d: d["by_rule"].update(X9=1),
    lambda d: d["findings"][0].update(severity="info"),
    lambda d: d["findings"][0].pop("counted"),
    lambda d: d.pop("gh_fetched_at"),
], ids=["version", "rule-id", "severity", "counted-required", "gh-fetched-at-required"])
def test_report_schema_rejects(mutate) -> None:
    bad = copy.deepcopy(REPORT)
    mutate(bad)
    assert _errors(REPORT_SCHEMA, bad)


@pytest.mark.parametrize("heading", ["### `catalogs/TodoCatalog.schema.json`",
                                     "### 7. `TodoSyncReport.schema.json`"])
def test_schemas_readme_documents_the_schemas(heading: str) -> None:
    assert heading in (SCHEMAS / "README.md").read_text(encoding="utf-8")
