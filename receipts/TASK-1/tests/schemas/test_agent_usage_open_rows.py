"""The agent usage schema takes any dispatch's row (issue #193).

A dispatch outside pr-review and pr-team names its own skill and role in its prompt header, and every header
key the watcher does not consume lands in an optional ``fields`` object of uppercase keys and string values of
at most 200 characters that hold no path separator: no local or absolute path enters the log (plan 0006 D8).
Rows written before the change still validate. ``signal`` reads ``NO_BLOCK`` for any agent without a return
block, not only a standalone one.
"""
from __future__ import annotations

import json

import jsonschema

from conftest import PLUGIN_ROOT

SCHEMA_FILE = PLUGIN_ROOT / "schemas" / "agent_usage.schema.json"


def _schema() -> dict:
    assert SCHEMA_FILE.is_file(), f"{SCHEMA_FILE} is missing"
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def _row(**extra) -> dict:
    row = {
        "logged_at": "2026-11-04T06:00:00.000Z", "run_id": "standalone_20261104T060000Z_1", "pr": None,
        "skill": "standalone", "role": "other", "agent_id": "strap-scenario-runner",
        "subagent_type": "harness:strap-scenario-runner", "model": "claude-sonnet-5-5",
        "model_family": "sonnet",
        "effort": "default", "tokens": 1000, "tool_uses": 7, "duration_s": 2.5, "signal": "recorded",
        "notes": "agent-watcher auto row; other recorded",
    }
    row.update(extra)
    return row


def _errors(row: dict) -> list:
    return [e.message for e in jsonschema.Draft7Validator(_schema()).iter_errors(row)]


def test_any_skill_name_validates() -> None:
    assert _errors(_row(skill="strap-skills")) == []
    assert _errors(_row(skill="pr-review", pr=35)) == []


def test_any_role_name_validates() -> None:
    assert _errors(_row(role="runner")) == []
    assert _errors(_row(role="judge")) == []
    assert _errors(_row(role="qa2")) == []


def test_a_fields_object_validates() -> None:
    assert _errors(_row(fields={"RUN": "R-3", "TARGET": "retry-policy", "ISSUE": "I2"})) == []
    assert _errors(_row()) == []


def test_fields_hold_uppercase_keys_and_string_values() -> None:
    assert "fields" in _schema()["properties"], "the schema has no fields property"
    assert _errors(_row(fields={"run": "R-3"})) != []
    assert _errors(_row(fields={"RUN": 3})) != []
    assert _errors(_row(skill="Strap Skills")) != []


def test_field_values_are_capped() -> None:
    assert _errors(_row(fields={"CONTEXT": "x" * 200})) == []
    assert _errors(_row(fields={"CONTEXT": "x" * 201})) != []


def test_field_values_hold_no_paths() -> None:
    assert _errors(_row(fields={"TREE": "tree"})) == []
    for value in ("/w/tree", "docs/strap/retry-policy.json", "C:\\work\\tree", "./x", "a/b"):
        assert _errors(_row(fields={"TREE": value})) != [], value


def test_signal_reads_without_standalone_framing() -> None:
    description = _schema()["properties"]["signal"]["description"]
    assert "NO_BLOCK" in description
    assert "standalone" not in description
