"""Behavioral tests for terminals.fixer.schema.json evidence constraints.

Covers Issue #1125 Acceptance Criteria:
  AC1  evidence.propertyNames validates against issue_id pattern (^[CIM][0-9]+$)
  AC2  evidence values are non-empty strings (minLength >= 1)
  AC3  DONE + non-empty fixed requires non-empty evidence (minProperties >= 1)
  AC4  DONE + empty fixed forbids evidence entirely
  AC5  schema descriptions contain no "comma-separated list" references to fixed
  AC6  qa_review_json.py check_c5_evidence_coverage enforces EXACT key correspondence (bidirectional —
       runtime only, not schema)
  AC7  fixer schema self-validates under Draft 2020-12
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

try:
    import jsonschema
    from referencing import Registry, Resource

    _HAS_DEPS = True
except ImportError:
    _HAS_DEPS = False

pytestmark = pytest.mark.skipif(
    not _HAS_DEPS, reason="jsonschema + referencing packages required"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pr_team_dir(plugin_root: Path) -> Path:
    path = plugin_root / "skills" / "pr-team"
    if not path.is_dir():
        pytest.fail(f"pr-team skill directory not found: {path}")
    return path


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        pytest.fail(f"Schema file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _build_fixer_validator(plugin_root: Path) -> jsonschema.Draft202012Validator:
    d = _pr_team_dir(plugin_root)
    common = _load_json(d / "terminals.common.schema.json")
    fixer = _load_json(d / "terminals.fixer.schema.json")
    registry = Registry().with_resources([
        ("terminals.common.schema.json", Resource.from_contents(common)),
    ])
    return jsonschema.Draft202012Validator(fixer, registry=registry)


def _base_done_row() -> Dict[str, Any]:
    return {
        "agent_id": "fixer_1",
        "agent_role": "fixer",
        "signal": "DONE",
        "fixed": ["C1"],
        "bubbled": [],
        "edited": 1,
        "output_path": "docs/fixer_1_output.md",
        "evidence": {"C1": "L42 rewritten; verified via Read post-edit"},
    }


def _iter_errors(v: jsonschema.Draft202012Validator, row: Dict[str, Any]) -> List[jsonschema.ValidationError]:
    return list(v.iter_errors(row))


# ---------------------------------------------------------------------------
# AC1: evidence property names must match the issue_id pattern ^[CIM][0-9]+$
# ---------------------------------------------------------------------------

class TestEvidencePropertyNames:

    def test_c_prefix_key_passes(self, plugin_root: Path) -> None:
        v = _build_fixer_validator(plugin_root)
        row = _base_done_row()
        row["fixed"] = ["C12"]
        row["evidence"] = {"C12": "patched at L88"}
        assert _iter_errors(v, row) == [], "C-prefix issue ID key should be a valid evidence key"

    def test_i_prefix_key_passes(self, plugin_root: Path) -> None:
        v = _build_fixer_validator(plugin_root)
        row = _base_done_row()
        row["fixed"] = ["I3"]
        row["evidence"] = {"I3": "infra fix applied"}
        assert _iter_errors(v, row) == [], "I-prefix issue ID key should be a valid evidence key"

    def test_m_prefix_key_passes(self, plugin_root: Path) -> None:
        v = _build_fixer_validator(plugin_root)
        row = _base_done_row()
        row["fixed"] = ["M7"]
        row["evidence"] = {"M7": "misc item resolved"}
        assert _iter_errors(v, row) == [], "M-prefix issue ID key should be a valid evidence key"

    def test_arbitrary_string_key_rejected(self, plugin_root: Path) -> None:
        v = _build_fixer_validator(plugin_root)
        row = _base_done_row()
        row["evidence"] = {"not_an_issue_id": "some claim"}
        errs = _iter_errors(v, row)
        assert any(e.validator == "pattern" for e in errs), (
            "Evidence key 'not_an_issue_id' does not match ^[CIM][0-9]+$ and must be rejected "
            "by pattern; expected a `pattern` keyword failure, got: "
            f"{[e.validator for e in errs]}"
        )

    def test_lowercase_prefix_key_rejected(self, plugin_root: Path) -> None:
        v = _build_fixer_validator(plugin_root)
        row = _base_done_row()
        row["evidence"] = {"c1": "lowercase prefix"}
        errs = _iter_errors(v, row)
        assert any(e.validator == "pattern" for e in errs), (
            "Lowercase 'c1' does not match ^[CIM][0-9]+$ and must be rejected; "
            "expected a `pattern` keyword failure, got: "
            f"{[e.validator for e in errs]}"
        )

    def test_numeric_only_key_rejected(self, plugin_root: Path) -> None:
        v = _build_fixer_validator(plugin_root)
        row = _base_done_row()
        row["evidence"] = {"123": "no prefix"}
        errs = _iter_errors(v, row)
        assert any(e.validator == "pattern" for e in errs), (
            "Numeric-only key '123' does not match ^[CIM][0-9]+$ and must be rejected; "
            "expected a `pattern` keyword failure, got: "
            f"{[e.validator for e in errs]}"
        )


# ---------------------------------------------------------------------------
# AC2: evidence values must be non-empty strings (minLength: 1)
# ---------------------------------------------------------------------------

class TestEvidenceValueConstraints:

    def test_non_empty_value_accepted(self, plugin_root: Path) -> None:
        v = _build_fixer_validator(plugin_root)
        row = _base_done_row()
        row["evidence"] = {"C1": "fix description here"}
        assert _iter_errors(v, row) == [], "Non-empty string evidence value must be accepted"

    def test_empty_string_value_rejected(self, plugin_root: Path) -> None:
        v = _build_fixer_validator(plugin_root)
        row = _base_done_row()
        row["evidence"] = {"C1": ""}
        errs = _iter_errors(v, row)
        assert any(e.validator == "minLength" for e in errs), (
            "Empty string evidence value must be rejected (minLength: 1); "
            "expected a `minLength` keyword failure, got: "
            f"{[e.validator for e in errs]}"
        )


# ---------------------------------------------------------------------------
# AC3: DONE + non-empty fixed requires non-empty evidence (minProperties: 1)
# AC4: DONE + empty fixed forbids evidence
# ---------------------------------------------------------------------------

class TestDoneEvidencePresenceRules:

    def test_done_nonempty_fixed_with_valid_evidence_accepted(self, plugin_root: Path) -> None:
        v = _build_fixer_validator(plugin_root)
        row = _base_done_row()
        assert _iter_errors(v, row) == [], "Baseline DONE row with valid evidence must be accepted"

    def test_done_nonempty_fixed_with_empty_evidence_object_rejected(self, plugin_root: Path) -> None:
        """AC3: evidence present but empty (zero keys) must fail when fixed is non-empty."""
        v = _build_fixer_validator(plugin_root)
        row = _base_done_row()
        row["evidence"] = {}
        errs = _iter_errors(v, row)
        assert any(e.validator == "minProperties" for e in errs), (
            "DONE row with non-empty fixed and empty evidence {} must be rejected "
            "(minProperties: 1 required by AC3); expected a `minProperties` keyword failure, got: "
            f"{[e.validator for e in errs]}"
        )

    def test_done_empty_fixed_without_evidence_accepted(self, plugin_root: Path) -> None:
        """AC4 control: DONE + empty fixed + no evidence is valid."""
        v = _build_fixer_validator(plugin_root)
        row = _base_done_row()
        row["fixed"] = []
        row.pop("evidence", None)
        assert _iter_errors(v, row) == [], "DONE with empty fixed and no evidence must be accepted"

    def test_done_empty_fixed_with_evidence_rejected(self, plugin_root: Path) -> None:
        """AC4: evidence must be omitted when fixed is empty."""
        v = _build_fixer_validator(plugin_root)
        row = _base_done_row()
        row["fixed"] = []
        row["evidence"] = {"C1": "stale key — should not be here"}
        errs = _iter_errors(v, row)
        assert any(e.validator == "not" for e in errs), (
            "DONE row with empty fixed and evidence present must be rejected (AC4); "
            "expected a `not` keyword failure, got: "
            f"{[e.validator for e in errs]}"
        )


# ---------------------------------------------------------------------------
# AC5: no "comma-separated list" wording in fixer schema descriptions/comments
# ---------------------------------------------------------------------------

class TestSchemaWordingAC5:

    def test_no_comma_separated_list_in_fixer_schema(self, plugin_root: Path) -> None:
        content = (_pr_team_dir(plugin_root) / "terminals.fixer.schema.json").read_text(
            encoding="utf-8"
        )
        assert "comma-separated list" not in content.lower(), (
            "terminals.fixer.schema.json must not describe 'fixed' as a comma-separated list; "
            "update wording to reference the array"
        )


# ---------------------------------------------------------------------------
# AC7: fixer schema itself validates under Draft 2020-12
# ---------------------------------------------------------------------------

class TestSchemaDraft202012:

    def test_fixer_schema_valid_under_draft_2020_12(self, plugin_root: Path) -> None:
        fixer = _load_json(_pr_team_dir(plugin_root) / "terminals.fixer.schema.json")
        try:
            jsonschema.Draft202012Validator.check_schema(fixer)
        except jsonschema.SchemaError as exc:
            pytest.fail(
                f"terminals.fixer.schema.json fails Draft 2020-12 meta-schema check: {exc.message}"
            )


# ---------------------------------------------------------------------------
# AC6: qa_review_json.py check_c5_evidence_coverage enforces EXACT (bidirectional)
#      key correspondence between evidence and fixed[].
#      Runtime check — not enforceable via JSON Schema directly.
# ---------------------------------------------------------------------------

def _load_qa_review_module(plugin_root: Path):
    """Load the plugin's skills/pr-team/commands/qa_review_json.py by file path.

    The pr-team commands tree lives outside scripts/ and uses a hyphenated
    directory name, so a regular `import` won't work — load via spec.
    """
    import importlib.util
    import sys
    target = plugin_root / "skills" / "pr-team" / "commands" / "qa_review_json.py"
    if not target.exists():
        pytest.fail(f"qa_review_json.py not found at {target}")
    spec = importlib.util.spec_from_file_location("qa_review_json_under_test", target)
    if spec is None or spec.loader is None:
        pytest.fail(f"Could not load spec for {target}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec_module: qa_review_json.py uses `from __future__ import
    # annotations`, so @dataclass resolves field annotations via
    # sys.modules[cls.__module__]. An unregistered by-path module makes that
    # lookup return None and dataclass processing raises AttributeError.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestAC6BidirectionalEvidence:
    """C5 (runtime, in qa_review_json.py) enforces exact key/value correspondence.

    Schema can only enforce propertyNames + minLength + presence (AC1-AC4);
    cross-field equality between evidence.keys() and fixed[] is the runtime
    check's job.
    """

    def _done_row(self, fixed, evidence):
        return {
            "agent_id": "fixer_ac6",
            "agent_role": "fixer",
            "signal": "DONE",
            "fixed": fixed,
            "bubbled": [],
            "edited": 1,
            "output_path": "docs/fixer_ac6_output.md",
            "evidence": evidence,
        }

    def test_exact_correspondence_passes(self, plugin_root: Path) -> None:
        qa = _load_qa_review_module(plugin_root)
        row = self._done_row(["C1", "I2"], {"C1": "claim a", "I2": "claim b"})
        ok, msg = qa.check_c5_evidence_coverage([row])
        assert ok, f"C5 should PASS when evidence keys exactly match fixed[]; got: {msg}"

    def test_missing_key_fails(self, plugin_root: Path) -> None:
        qa = _load_qa_review_module(plugin_root)
        row = self._done_row(["C1", "I2"], {"C1": "claim a"})  # missing I2
        ok, msg = qa.check_c5_evidence_coverage([row])
        assert not ok, "C5 should FAIL when evidence is missing a key for a fixed id"
        assert "missing" in msg.lower(), f"FAIL message should mention 'missing'; got: {msg}"

    def test_extra_key_fails(self, plugin_root: Path) -> None:
        qa = _load_qa_review_module(plugin_root)
        row = self._done_row(["C1"], {"C1": "claim a", "C99": "stale claim"})  # extra C99
        ok, msg = qa.check_c5_evidence_coverage([row])
        assert not ok, "C5 should FAIL when evidence has an extra key not in fixed[]"
        assert "extra" in msg.lower(), f"FAIL message should mention 'extra'; got: {msg}"

    def test_empty_fixed_skipped(self, plugin_root: Path) -> None:
        qa = _load_qa_review_module(plugin_root)
        # DONE with empty fixed: per schema AC4, evidence MUST be absent. C5 only
        # examines rows with non-empty fixed, so this row should PASS at C5 level
        # regardless of evidence presence (schema AC4 catches the evidence-presence
        # violation; C5 is concerned with key correspondence).
        row = self._done_row([], {})
        row.pop("evidence")  # match schema AC4 expectation
        ok, msg = qa.check_c5_evidence_coverage([row])
        assert ok, f"C5 should PASS (skip) for DONE row with empty fixed; got: {msg}"
