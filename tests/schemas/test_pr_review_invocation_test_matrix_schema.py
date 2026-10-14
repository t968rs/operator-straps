"""Schema discipline for the pr-review invocation test matrix
(``pr_review_invocation_test_matrix.schema.json``).

Pins three contracts:
  1. Every row of a vendored sample JSONL (``tests/fixtures/``) validates against the schema.
  2. The `dispatch_shape` field is required and accepts `parallel` (Phase 2 reviewer
     fan-out) or `inline` (orchestrator running solo, no fan-out).
  3. Unknown values are rejected, and the field cannot be omitted.

A project's live matrix (``<project>/<matrix_path>``) is that project's data; its rows are not
validated here.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from conftest import FIXTURES, PLUGIN_ROOT

_SCHEMA_FILE = PLUGIN_ROOT / "schemas" / "pr_review_invocation_test_matrix.schema.json"
_SAMPLE_ROWS = FIXTURES / "pr_review_invocation_test_matrix_rows.jsonl"


def _load_schema() -> dict:
    return json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))


def _load_rows(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _minimal_valid_row() -> dict:
    """A skeleton row that satisfies the *current* required-field set.

    dev_commit is a syntactically-valid 40-char hex SHA so the row passes the
    Cycle-12 conditional pattern by default. Tests that exercise the legacy
    branch override this field explicitly.
    """
    return {
        "cell": "test_cell",
        "pr": 1,
        "model_family": "haiku",
        "effort": "default",
        "dev_commit": "0123456789abcdef0123456789abcdef01234567",  # placeholder SHA shape
        "tokens": 0,
        "tool_uses": 0,
        "duration_s": 0.0,
        "findings_count": 0,
        "C_count": 0,
        "I_count": 0,
        "M_count": 0,
        "other_count": 0,
        "verdict_prefix": "READY TO MERGE",
        "notes": "test",
    }


def test_legacy_model_field_rejected():
    """Rows carrying the old `model` key (without `model_family`) are rejected.

    Pins the contract that the schema field was renamed from `model` to
    `model_family` and the old field name is no longer accepted (schema has
    `additionalProperties: false`).
    """
    schema = _load_schema()
    row = _minimal_valid_row()
    row.pop("model_family")
    row["model"] = "haiku"  # legacy field name with valid value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(row, schema)


def test_every_sample_jsonl_row_validates():
    """Every row of the vendored sample JSONL validates (parallel, inline and legacy shapes)."""
    schema = _load_schema()
    rows = _load_rows(_SAMPLE_ROWS)
    assert {r["dispatch_shape"] for r in rows} == {"parallel", "inline"}
    assert any(r.get("legacy") is True for r in rows)
    for idx, row in enumerate(rows, start=1):
        try:
            jsonschema.validate(row, schema)
        except jsonschema.ValidationError as exc:
            pytest.fail(
                f"row {idx} (cell={row.get('cell', '<missing>')}) failed schema: {exc.message}"
            )


def test_parallel_dispatch_shape_validates():
    """A row with dispatch_shape='parallel' validates."""
    schema = _load_schema()
    row = _minimal_valid_row()
    row["dispatch_shape"] = "parallel"
    jsonschema.validate(row, schema)  # must not raise


def test_inline_dispatch_shape_validates():
    """A row with dispatch_shape='inline' validates."""
    schema = _load_schema()
    row = _minimal_valid_row()
    row["dispatch_shape"] = "inline"
    jsonschema.validate(row, schema)  # must not raise


def test_unknown_dispatch_shape_rejected():
    """Unknown dispatch_shape values fail validation."""
    schema = _load_schema()
    row = _minimal_valid_row()
    row["dispatch_shape"] = "garbage"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(row, schema)


def test_missing_dispatch_shape_rejected():
    """Rows must declare dispatch_shape — implicit/default is not allowed.

    Pins the contract that downstream analysis can pivot on dispatch_shape
    without needing a fillna or default-assumption step.
    """
    schema = _load_schema()
    row = _minimal_valid_row()  # no dispatch_shape
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(row, schema)


# ---------------------------------------------------------------------------
# dev_commit hardening (Cycle 12). Two regimes:
#  * legacy: true  -> dev_commit is freetext (grandfathers narrative-only rows
#                     like "dev (pre-#916)" / "main (pre-rename)" that have no
#                     anchorable SHA in git history)
#  * legacy: false (or absent, default-false) -> dev_commit must start with a
#                     40-char lowercase hex SHA, optionally followed by " -- "
#                     and freetext suffix
# ---------------------------------------------------------------------------


_VALID_SHA = "b3526dbe19f4803237e70a92550fd9ee39e46edc"


def test_legacy_true_allows_freetext_dev_commit():
    """legacy:true rows accept freetext (grandfathered narrative anchors)."""
    schema = _load_schema()
    row = _minimal_valid_row()
    row["dispatch_shape"] = "parallel"
    row["legacy"] = True
    row["dev_commit"] = "dev (pre-#916)"  # narrative; no SHA
    jsonschema.validate(row, schema)  # must not raise


def test_legacy_false_requires_sha_prefix():
    """legacy:false rows require a 40-char hex SHA prefix in dev_commit."""
    schema = _load_schema()
    row = _minimal_valid_row()
    row["dispatch_shape"] = "parallel"
    row["legacy"] = False
    row["dev_commit"] = "1913-SKILL-pr_review_hooks (current)"  # no SHA
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(row, schema)


def test_legacy_omitted_requires_sha_prefix():
    """When legacy is omitted (default false), dev_commit must be SHA-prefixed."""
    schema = _load_schema()
    row = _minimal_valid_row()
    row["dispatch_shape"] = "parallel"
    row["dev_commit"] = "main (pre-rename)"  # no SHA, no legacy field
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(row, schema)


def test_pure_sha_dev_commit_validates():
    """A bare 40-hex-char SHA is the minimal valid new-format dev_commit."""
    schema = _load_schema()
    row = _minimal_valid_row()
    row["dispatch_shape"] = "parallel"
    row["dev_commit"] = _VALID_SHA
    jsonschema.validate(row, schema)  # must not raise


def test_sha_with_freetext_suffix_validates():
    """The recommended new-format is `<sha> -- <label>`."""
    schema = _load_schema()
    row = _minimal_valid_row()
    row["dispatch_shape"] = "parallel"
    row["dev_commit"] = f"{_VALID_SHA} -- 1913-SKILL-pr_review_hooks (rerun)"
    jsonschema.validate(row, schema)  # must not raise


def test_uppercase_or_nonhex_sha_prefix_rejected():
    """Pattern is lowercase hex only — uppercase or non-hex chars fail."""
    schema = _load_schema()
    row = _minimal_valid_row()
    row["dispatch_shape"] = "parallel"
    row["dev_commit"] = "X" * 40  # 40 chars but not hex
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(row, schema)


def test_unknown_legacy_value_rejected():
    """legacy is a strict boolean — strings like 'true' or other truthy values fail."""
    schema = _load_schema()
    row = _minimal_valid_row()
    row["dispatch_shape"] = "parallel"
    row["legacy"] = "true"  # string, not boolean
    row["dev_commit"] = _VALID_SHA
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(row, schema)
