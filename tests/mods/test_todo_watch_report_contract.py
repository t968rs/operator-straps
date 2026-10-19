"""Pin the keys the todo-watch mod reads from a sync report to ``TodoSyncReport.schema.json``.

The mod parses ``<state_dir>/todo-sync/report.json`` in TypeScript
(``plugins/todo-watch/hooks/checks.ts``: ``REPORT_KEYS``, ``COUNT_KEYS``, ``FINDING_KEYS``,
``FINDING_REQUIRED``, ``SEVERITIES``, ``REPORT_SCHEMA_VERSION``), where the plugin test sandbox cannot read
repository files. This test reads both sides and fails when
``plugins/harness/schemas/TodoSyncReport.schema.json`` drops, renames or makes optional a key the mod
reads, or changes the version or severity enum, without the mod following.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mods._mods_helpers import ts_number, ts_string_array

_SCHEMA_REL = "plugins/harness/schemas/TodoSyncReport.schema.json"
_CHECKS_TS_REL = "plugins/todo-watch/hooks/checks.ts"


@pytest.fixture(scope="module")
def schema(repo_root: Path) -> dict:
    return json.loads((repo_root / _SCHEMA_REL).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def checks_ts(repo_root: Path) -> str:
    return (repo_root / _CHECKS_TS_REL).read_text(encoding="utf-8")


def test_report_keys_are_required_by_the_schema(schema: dict, checks_ts: str) -> None:
    keys = ts_string_array(checks_ts, "REPORT_KEYS")
    assert keys
    assert set(keys) <= set(schema["required"])


def test_schema_version_matches(schema: dict, checks_ts: str) -> None:
    assert ts_number(checks_ts, "REPORT_SCHEMA_VERSION") == schema["properties"]["schema_version"]["const"]


def test_count_keys_match(schema: dict, checks_ts: str) -> None:
    counts = schema["properties"]["counts"]
    assert ts_string_array(checks_ts, "COUNT_KEYS") == counts["required"]
    assert set(counts["properties"]) == set(counts["required"])


def test_finding_keys_exist(schema: dict, checks_ts: str) -> None:
    finding = schema["$defs"]["finding"]
    assert set(ts_string_array(checks_ts, "FINDING_KEYS")) == set(finding["properties"])


def test_finding_required_matches(schema: dict, checks_ts: str) -> None:
    finding = schema["$defs"]["finding"]
    assert ts_string_array(checks_ts, "FINDING_REQUIRED") == finding["required"]


def test_severities_match(schema: dict, checks_ts: str) -> None:
    expected = schema["$defs"]["finding"]["properties"]["severity"]["enum"]
    assert ts_string_array(checks_ts, "SEVERITIES") == expected


def test_nullable_fields_the_mod_defaults(schema: dict) -> None:
    """``file``, ``subject``, ``fix`` and ``gh_fetched_at`` may be null; the mod maps null to null."""
    finding = schema["$defs"]["finding"]["properties"]
    for key in ("file", "subject", "fix"):
        assert "null" in finding[key]["type"], key
    assert "null" in schema["properties"]["gh_fetched_at"]["type"]
