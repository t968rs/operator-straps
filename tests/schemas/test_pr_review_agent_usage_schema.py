"""Schema discipline for the agent usage log (``pr_review_agent_usage.schema.json``).

Pins the row contract the pr-review-watch mod writes: every role validates, nullable fields accept null,
the four fixer count fields are required on fixer and closer rows and rejected on every other role, and
unknown keys, roles, families and malformed timestamps are rejected.

A project's live usage log (``<project>/<agent_usage_path>``) is that project's data; its rows are not
validated here.
"""
from __future__ import annotations

import json

import jsonschema
import pytest

from conftest import PLUGIN_ROOT

_SCHEMA_FILE = PLUGIN_ROOT / "schemas" / "pr_review_agent_usage.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))


def _row(role: str = "reviewer", **extra) -> dict:
    row = {
        "logged_at": "2026-10-20T21:00:00.000Z", "run_id": "pr35_20261020T210000Z", "pr": 35,
        "skill": "pr-review", "role": role, "agent_id": "runtime", "subagent_type": "harness:pr-reviewer",
        "model": "claude-opus-5-5", "model_family": "opus", "effort": "default", "tokens": 1000,
        "tool_uses": 7, "duration_s": 2.5, "signal": "DONE",
        "notes": "pr-review-watch auto row; reviewer DONE",
    }
    if role in ("fixer", "closer"):
        row.update(issues_assigned=2, issues_fixed=1, issues_bubbled=1, files_touched=3)
    row.update(extra)
    return row


@pytest.mark.parametrize("role", ["reviewer", "fixer", "orchestrator", "planner", "closer"])
def test_every_role_validates(schema: dict, role: str) -> None:
    jsonschema.validate(_row(role), schema)


def test_null_pr_subagent_type_model_and_counts_validate(schema: dict) -> None:
    row = _row("fixer", pr=None, subagent_type=None, model=None, model_family="unknown", issues_assigned=None,
               issues_fixed=None, issues_bubbled=None, files_touched=None)
    jsonschema.validate(row, schema)


def test_pr_team_skill_validates(schema: dict) -> None:
    jsonschema.validate(_row("orchestrator", skill="pr-team", agent_id="orchestrator_plan"), schema)


@pytest.mark.parametrize("row", [
    pytest.param(_row(issues_fixed=1), id="count-field-on-a-reviewer-row"),
    pytest.param({k: v for k, v in _row("fixer").items() if k != "issues_fixed"},
                 id="fixer-row-without-counts"),
    pytest.param(_row(model_family="fable"), id="unknown-family-token"),
    pytest.param(_row(tokens=-1), id="negative-tokens"),
    pytest.param(_row(cell="x"), id="unknown-key"),
    pytest.param(_row(role="roaster"), id="unknown-role"),
    pytest.param(_row(logged_at="2026-10-20 21:00"), id="logged-at-not-utc-iso"),
])
def test_rejected_rows(schema: dict, row: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(row, schema)
