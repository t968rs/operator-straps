"""Pin the pr-review-watch mod's usage-row validator to the harness agent usage JSON schema.

The mod validates agent usage rows in TypeScript (``plugins/pr-review-watch/hooks/usageRow.ts``), where the
plugin test sandbox cannot read repository files. This test reads both sides and fails when
``plugins/harness/schemas/pr_review_agent_usage.schema.json`` changes its required fields, count fields,
enums or ``logged_at`` pattern without the mod following.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mods._mods_helpers import ts_string, ts_string_array

_SCHEMA_REL = "plugins/harness/schemas/pr_review_agent_usage.schema.json"
_USAGE_ROW_REL = "plugins/pr-review-watch/hooks/usageRow.ts"


@pytest.fixture(scope="module")
def schema(repo_root: Path) -> dict:
    return json.loads((repo_root / _SCHEMA_REL).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def usage_row_ts(repo_root: Path) -> str:
    return (repo_root / _USAGE_ROW_REL).read_text(encoding="utf-8")


def test_required_fields_match(schema: dict, usage_row_ts: str) -> None:
    assert ts_string_array(usage_row_ts, "USAGE_REQUIRED") == schema["required"]


def test_count_fields_are_the_conditional_rest(schema: dict, usage_row_ts: str) -> None:
    counts = ts_string_array(usage_row_ts, "USAGE_COUNT_FIELDS")
    assert counts == schema["then"]["required"]
    assert set(schema["properties"]) - set(schema["required"]) == set(counts)


def test_roles_match(schema: dict, usage_row_ts: str) -> None:
    assert ts_string_array(usage_row_ts, "USAGE_ROLES") == schema["properties"]["role"]["enum"]
    assert ts_string_array(usage_row_ts, "USAGE_COUNTED_ROLES") == schema["if"]["properties"]["role"]["enum"]


def test_skills_match(schema: dict, usage_row_ts: str) -> None:
    assert ts_string_array(usage_row_ts, "USAGE_SKILLS") == schema["properties"]["skill"]["enum"]


def test_model_families_match(schema: dict, usage_row_ts: str) -> None:
    expected = schema["properties"]["model_family"]["enum"]
    assert ts_string_array(usage_row_ts, "USAGE_MODEL_FAMILIES") == expected


def test_logged_at_pattern_matches(schema: dict, usage_row_ts: str) -> None:
    assert ts_string(usage_row_ts, "LOGGED_AT_PATTERN") == schema["properties"]["logged_at"]["pattern"]
