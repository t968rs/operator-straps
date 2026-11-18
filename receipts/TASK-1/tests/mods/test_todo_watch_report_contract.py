"""Pin the keys the todo-watch mod reads from a sync report and the runner pointer to the harness side.

The mod parses ``<state_dir>/todo-sync/report.json`` and ``runner.json`` in TypeScript
(``plugins/todo-watch/hooks/checks.ts``: ``REPORT_KEYS``, ``COUNT_KEYS``, ``FINDING_KEYS``,
``FINDING_REQUIRED``, ``SEVERITIES``, ``REPORT_SCHEMA_VERSION``, ``SUBSET_REASON``, ``RUNNER_KEYS``,
``RUNNER_SCHEMA_VERSION``), where the plugin test sandbox cannot read repository files. This test reads
both sides and fails when ``plugins/harness/schemas/TodoSyncReport.schema.json`` drops, renames or makes
optional a key the mod reads, changes the version or severity enum, or when ``write_runner`` (in
``todo_sync/__init__.py``) stops writing a key or version ``parseRunner`` requires, without the mod
following. It also checks that the finding parser reads every finding key through ``FINDING_KEYS`` and
the severity through ``SEVERITIES``, so the constants are the parser's own keys.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from harness_lib.config import load_config
from harness_lib.todo_sync import write_runner
from mods._mods_helpers import ts_number, ts_string, ts_string_array

_SCHEMA_REL = "plugins/harness/schemas/TodoSyncReport.schema.json"
_CHECKS_TS_REL = "plugins/todo-watch/hooks/checks.ts"
_ENGINE_REL = "plugins/harness/lib/harness_lib/todo_sync/__init__.py"


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


def test_finding_parser_reads_through_the_constants(checks_ts: str) -> None:
    """``findingOf`` reads exactly ``FINDING_KEYS`` through ``field``; ``SEVERITIES`` checks severity."""
    read = set(re.findall(r"field\(v, '(\w+)'\)", checks_ts))
    assert read == set(ts_string_array(checks_ts, "FINDING_KEYS"))
    assert "SEVERITIES.some(" in checks_ts
    assert "severity !== '" not in checks_ts


def test_subset_reason_matches_the_engine(repo_root: Path, checks_ts: str) -> None:
    engine = (repo_root / _ENGINE_REL).read_text(encoding="utf-8")
    assert f'"{ts_string(checks_ts, "SUBSET_REASON")}"' in engine


def test_runner_pointer_matches_write_runner(make_project, checks_ts: str) -> None:
    cfg = load_config(make_project({"todo": {"folder": "docs/T"}}))
    pointer = json.loads(write_runner(cfg).read_text(encoding="utf-8"))
    assert pointer["schema_version"] == ts_number(checks_ts, "RUNNER_SCHEMA_VERSION")
    for key in (*ts_string_array(checks_ts, "RUNNER_KEYS"), "report"):
        assert isinstance(pointer.get(key), str) and pointer[key].strip(), key


def test_nullable_fields_the_mod_defaults(schema: dict) -> None:
    """``file``, ``subject``, ``line``, ``fix`` and ``gh_fetched_at`` may be null; the mod keeps null."""
    finding = schema["$defs"]["finding"]["properties"]
    for key in ("file", "subject", "line", "fix"):
        assert "null" in finding[key]["type"], key
    assert "null" in schema["properties"]["gh_fetched_at"]["type"]
