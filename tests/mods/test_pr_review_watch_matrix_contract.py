"""Pin the pr-review-watch mod's matrix-row validator to the harness matrix JSON schema.

The mod validates invocation-matrix rows in TypeScript (``plugins/pr-review-watch/hooks/matrixRow.ts``,
family enum in ``plugins/pr-review-watch/hooks/contract.ts``), where the plugin test sandbox cannot read
repository files. This test reads both sides and fails when
``plugins/harness/schemas/pr_review_invocation_test_matrix.schema.json`` changes its required fields, enums
or ``dev_commit`` pattern without the mod following.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mods._mods_helpers import ts_string, ts_string_array

_SCHEMA_REL = "plugins/harness/schemas/pr_review_invocation_test_matrix.schema.json"
_MATRIX_ROW_REL = "plugins/pr-review-watch/hooks/matrixRow.ts"
_CONTRACT_REL = "plugins/pr-review-watch/hooks/contract.ts"


@pytest.fixture(scope="module")
def schema(repo_root: Path) -> dict:
    return json.loads((repo_root / _SCHEMA_REL).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def matrix_row_ts(repo_root: Path) -> str:
    return (repo_root / _MATRIX_ROW_REL).read_text(encoding="utf-8")


def test_required_fields_match(schema: dict, matrix_row_ts: str) -> None:
    assert ts_string_array(matrix_row_ts, "MATRIX_REQUIRED") == schema["required"]


def test_optional_fields_cover_the_rest(schema: dict, matrix_row_ts: str) -> None:
    optional = set(schema["properties"]) - set(schema["required"])
    assert set(ts_string_array(matrix_row_ts, "MATRIX_OPTIONAL")) == optional


def test_dispatch_shapes_match(schema: dict, matrix_row_ts: str) -> None:
    expected = schema["properties"]["dispatch_shape"]["enum"]
    assert ts_string_array(matrix_row_ts, "DISPATCH_SHAPES") == expected


def test_dev_commit_pattern_matches(schema: dict, matrix_row_ts: str) -> None:
    expected = schema["else"]["properties"]["dev_commit"]["pattern"]
    assert ts_string(matrix_row_ts, "DEV_COMMIT_PATTERN") == expected


def test_model_families_match(schema: dict, repo_root: Path) -> None:
    contract_ts = (repo_root / _CONTRACT_REL).read_text(encoding="utf-8")
    expected = schema["properties"]["model_family"]["enum"]
    assert ts_string_array(contract_ts, "MODEL_FAMILIES") == expected
