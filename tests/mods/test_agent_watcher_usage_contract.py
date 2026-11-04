"""Pin the agent-watcher mod's usage-row validator to the harness agent usage JSON schema.

The mod validates agent usage rows in TypeScript (``plugins/agent-watcher/hooks/core/usageRow.ts``), where
the plugin test sandbox cannot read repository files. This test reads both sides and fails when
``plugins/harness/schemas/agent_usage.schema.json`` changes its required fields, count fields, optional
``fields`` object and its key, length and no-path rules, the skill and role patterns, the model family enum,
``logged_at`` pattern, nullable strings or non-empty strings without the mod following.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mods._mods_helpers import ts_number, ts_string, ts_string_array

WALK_ROOTS = ("plugins/",)
_SCHEMA_REL = "plugins/harness/schemas/agent_usage.schema.json"
_USAGE_ROW_REL = "plugins/agent-watcher/hooks/core/usageRow.ts"
_CONTRACT_REL = "plugins/agent-watcher/hooks/core/contract.ts"


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
    optional = ts_string_array(usage_row_ts, "USAGE_OPTIONAL")
    assert counts == schema["then"]["required"]
    assert set(schema["properties"]) - set(schema["required"]) == set(counts) | set(optional)
    assert optional == ["fields"]


def test_role_pattern_matches(schema: dict, usage_row_ts: str) -> None:
    assert ts_string(usage_row_ts, "ROLE_PATTERN") == schema["properties"]["role"]["pattern"]
    assert "enum" not in schema["properties"]["role"]
    assert ts_string_array(usage_row_ts, "USAGE_COUNTED_ROLES") == schema["if"]["properties"]["role"]["enum"]


def test_skill_pattern_matches(schema: dict, usage_row_ts: str) -> None:
    assert ts_string(usage_row_ts, "SKILL_PATTERN") == schema["properties"]["skill"]["pattern"]
    assert "enum" not in schema["properties"]["skill"]


def _ts_literal(source: str, name: str) -> str:
    """The value of a single-quoted TS string constant, its ``\\\\`` escapes undone."""
    return ts_string(source, name).replace("\\\\", "\\")


def test_fields_rule_matches(schema: dict, usage_row_ts: str) -> None:
    fields = schema["properties"]["fields"]
    assert fields["type"] == "object"
    assert ts_string(usage_row_ts, "FIELD_KEY_PATTERN") == fields["propertyNames"]["pattern"]
    values = fields["additionalProperties"]
    assert values["type"] == "string"
    assert ts_number(usage_row_ts, "FIELD_VALUE_MAX") == values["maxLength"] == 200
    assert _ts_literal(usage_row_ts, "FIELD_VALUE_PATTERN") == values["pattern"] == "^[^/\\\\]*$"


def test_path_free_columns_match(schema: dict, usage_row_ts: str) -> None:
    columns = ts_string_array(usage_row_ts, "PATH_FREE_COLUMNS")
    assert columns == ["run_id", "agent_id", "signal", "notes"]
    for column in columns:
        assert schema["properties"][column]["pattern"] == "^[^/\\\\]*$", column
    assert ts_number(usage_row_ts, "FIELD_VALUE_MAX") == schema["properties"]["signal"]["maxLength"]


def test_model_families_match(schema: dict, usage_row_ts: str) -> None:
    expected = schema["properties"]["model_family"]["enum"]
    assert ts_string_array(usage_row_ts, "USAGE_MODEL_FAMILIES") == expected


def test_logged_at_pattern_matches(schema: dict, usage_row_ts: str) -> None:
    assert ts_string(usage_row_ts, "LOGGED_AT_PATTERN") == schema["properties"]["logged_at"]["pattern"]


def test_nullable_strings_match(schema: dict, usage_row_ts: str) -> None:
    expected = [k for k, p in schema["properties"].items() if p.get("type") == ["string", "null"]]
    assert ts_string_array(usage_row_ts, "NULLABLE_STRINGS") == expected


def test_non_empty_strings_match(schema: dict, usage_row_ts: str) -> None:
    expected = [k for k, p in schema["properties"].items() if p.get("minLength") == 1]
    assert ts_string_array(usage_row_ts, "NON_EMPTY") == expected


def _defined_agents(repo_root: Path) -> list:
    """``<plugin>:<name>`` for every agent file under ``plugins/*/agents/``, as Claude Code names the type."""
    found = []
    for agent in sorted((repo_root / "plugins").glob("*/agents/*.md")):
        plugin = json.loads((agent.parents[1] / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        front = re.search(r"^name:\s*(\S+)\s*$", agent.read_text(encoding="utf-8"), re.MULTILINE)
        assert front is not None, f"{agent} has no name: frontmatter"
        assert front.group(1) == agent.stem, f"{agent} names itself {front.group(1)!r}, not its file stem"
        found.append(f"{plugin['name']}:{agent.stem}")
    return found


def test_defined_agents_cover_every_agent_file(repo_root: Path) -> None:
    contract_ts = (repo_root / _CONTRACT_REL).read_text(encoding="utf-8")
    defined = _defined_agents(repo_root)
    assert defined, "no agent files found under plugins/*/agents"
    assert ts_string_array(contract_ts, "DEFINED_AGENTS") == defined


def test_fallback_vocabulary_matches_the_patterns(schema: dict) -> None:
    assert re.fullmatch(schema["properties"]["role"]["pattern"], "other")
    assert re.fullmatch(schema["properties"]["skill"]["pattern"], "standalone")
    for role in ("reviewer", "fixer", "orchestrator", "planner", "closer"):
        assert re.fullmatch(schema["properties"]["role"]["pattern"], role), role
    for skill in ("pr-review", "pr-team"):
        assert re.fullmatch(schema["properties"]["skill"]["pattern"], skill), skill
