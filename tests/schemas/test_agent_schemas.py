"""Agent-schema discipline: schema shape contracts plus validation of vendored sample artifacts.

Schema-shape tests read the plugin's canonical schemas. Artifact tests place the vendored samples in
``tests/fixtures/agent_schemas/`` into a ``make_project`` project at its configured review and plan
directories, then validate them through ``schema_path`` and the sibling-schema registry, the same
resolution the schema hook uses. A consuming project's own artifacts are that project's data and are
not validated here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import jsonschema
import pytest
import referencing
import referencing.exceptions

from conftest import FIXTURES
from harness_lib.config import HarnessConfig, activate, load_config
from harness_lib.validation.artifact_names import is_review_artifact_name
from harness_lib.validation.schema_registry import load_schema, schema_registry

_SAMPLES = FIXTURES / "agent_schemas"
_REVIEW_SAMPLE = "0001_sample_review.json"
_PLAN_SAMPLE = "0001_sample_ActionPlan.json"


def _sample(name: str) -> Dict[str, Any]:
    return json.loads((_SAMPLES / name).read_text(encoding="utf-8"))


def _project_cfg(make_project, extra: Optional[Dict[str, Any]] = None) -> HarnessConfig:
    """A project holding both samples (plus ``extra`` files) at the configured artifact directories."""
    files: Dict[str, Any] = {f"docs/PR_REVIEWS/{_REVIEW_SAMPLE}": _sample(_REVIEW_SAMPLE),
                             f"docs/PLANS/{_PLAN_SAMPLE}": _sample(_PLAN_SAMPLE)}
    files.update(extra or {})
    return activate(load_config(make_project(files=files)))


def _review_files(cfg: HarnessConfig) -> List[Path]:
    return sorted(
        p for p in cfg.path(cfg.artifacts.reviews).glob("*.json") if is_review_artifact_name(p.name)
    )


def _plan_files(cfg: HarnessConfig) -> List[Path]:
    return sorted(p for p in cfg.path(cfg.artifacts.plans).glob("*.json") if "ActionPlan" in p.name)


def _violation(path: Path, schema_name: str, cfg: HarnessConfig) -> Optional[str]:
    """Validation message for ``path`` against ``schema_name`` (sibling refs resolved), else None."""
    schema = load_schema(schema_name, cfg)
    validator = jsonschema.validators.validator_for(schema)(schema, registry=schema_registry(cfg))
    instance = json.loads(path.read_text(encoding="utf-8"))
    error = jsonschema.exceptions.best_match(validator.iter_errors(instance))
    return None if error is None else f"{path.name}: {error.message}"


def validate_issue_location(entry: dict) -> Tuple[Optional[str], bool]:
    """Semantic rule on an issue's ``file`` / ``files`` keys, layered over the permissive schema ``anyOf``.

    ``file`` only or ``files`` only is valid; both is valid but deprecated when ``file == files[0]``,
    invalid otherwise; neither is invalid. Returns ``(error or None, deprecated)``.
    """
    has_f, has_fs = "file" in entry, "files" in entry
    if not has_f and not has_fs:
        return ("missing location: provide `file` or `files`", False)
    if not (has_f and has_fs):
        return (None, False)
    f, fs = entry.get("file"), entry.get("files")
    if not isinstance(fs, list) or len(fs) == 0:
        return (f"`files` must be a non-empty array, got {fs!r}", False)
    if f != fs[0]:
        return (f"`file` ({f!r}) must equal `files[0]` ({fs[0]!r}) when both keys are present", False)
    return (None, True)


def _issue_entries(report: Dict[str, Any]) -> Iterator[dict]:
    issues = report.get("issues", {})
    buckets = issues.values() if isinstance(issues, dict) else [issues]
    for bucket in buckets:
        if isinstance(bucket, list):
            yield from (e for e in bucket if isinstance(e, dict))


# ---------------------------------------------------------------------------
# Schema shape
# ---------------------------------------------------------------------------

def test_schema_files_exist(plugin_root: Path) -> None:
    """The canonical review, plan and PR-attribute schemas ship with the plugin."""
    for name in ("PR_REVIEW.schema.json", "ActionPlan.schema.json", "prAttributes.schema.json"):
        assert (plugin_root / "schemas" / name).is_file(), f"{name} missing from the plugin schemas"


def test_action_plan_schema_documents_json_markdown_split(make_project) -> None:
    """ActionPlan schema includes fields for verification references + markdown linkage."""
    schema = load_schema("ActionPlan.schema.json", activate(load_config(make_project())))
    top_props = schema.get("properties", {})
    item_props = schema.get("definitions", {}).get("action_item", {}).get("properties", {})
    assert "markdown_sync_status" in top_props
    assert "markdown_last_updated" in top_props
    assert "verification_references" in item_props
    assert "markdown_section" in item_props
    assert set(top_props["markdown_sync_status"]["enum"]) == {"pending_markdown_sync", "in_sync", None}
    assert top_props["markdown_last_updated"]["format"] == "date"
    assert set(top_props["markdown_last_updated"]["type"]) == {"string", "null"}
    assert item_props["verification_references"]["type"] == "array"
    assert item_props["verification_references"]["items"]["type"] == "string"
    assert set(item_props["markdown_section"]["type"]) == {"string", "null"}


def test_pip_template_documents_json_markdown_contract(plugin_root: Path) -> None:
    """PIP template must codify JSON source-of-truth and markdown expansion rules."""
    text = (plugin_root / "schemas" / "PLANS_PIP_Template.md").read_text(encoding="utf-8")
    assert "## JSON ↔ Markdown Contract" in text
    assert "items[].verification_references" in text
    assert "items[].markdown_section" in text


def test_pr_review_schema_models_fix_as_array_of_options(make_project) -> None:
    """Issue fixes are arrays of one-or-more remediation options."""
    schema = load_schema("PR_REVIEW.schema.json", activate(load_config(make_project())))
    fix_props = schema["definitions"]["issue"]["properties"]["fix"]
    assert fix_props["type"] == "array"
    assert fix_props["minItems"] == 1
    assert fix_props["items"]["type"] == "string"


# ---------------------------------------------------------------------------
# Vendored sample artifacts
# ---------------------------------------------------------------------------

def test_sample_review_validates(make_project) -> None:
    """The sample review validates against PR_REVIEW.schema.json from its project location."""
    cfg = _project_cfg(make_project)
    files = _review_files(cfg)
    assert [p.name for p in files] == [_REVIEW_SAMPLE]
    assert [v for v in (_violation(p, "PR_REVIEW.schema.json", cfg) for p in files) if v] == []


def test_sample_action_plan_validates(make_project) -> None:
    """The sample plan validates against ActionPlan.schema.json, prAttributes ref included."""
    cfg = _project_cfg(make_project)
    files = _plan_files(cfg)
    assert [p.name for p in files] == [_PLAN_SAMPLE]
    assert [v for v in (_violation(p, "ActionPlan.schema.json", cfg) for p in files) if v] == []


def test_sample_action_plan_exercises_the_sibling_ref(make_project) -> None:
    """Non-vacuity guard: the sample's ``pr_attributes`` cannot validate without the sibling registry."""
    cfg = activate(load_config(make_project()))
    schema = load_schema("ActionPlan.schema.json", cfg)
    validator = jsonschema.validators.validator_for(schema)(schema, registry=referencing.Registry())
    with pytest.raises(referencing.exceptions.Unresolvable, match="prAttributes.schema.json"):
        validator.validate(_sample(_PLAN_SAMPLE))


def test_plan_sibling_ref_violation_is_reported(make_project) -> None:
    """A ``pr_attributes`` entry missing ``pr`` is caught through the resolved prAttributes schema."""
    broken = dict(_sample(_PLAN_SAMPLE), plan_id="0002", pr_attributes=[{"bogus": 1}])
    cfg = _project_cfg(make_project, {"docs/PLANS/0002_broken_ActionPlan.json": broken})
    violations = [v for v in (_violation(p, "ActionPlan.schema.json", cfg) for p in _plan_files(cfg)) if v]
    assert violations == ["0002_broken_ActionPlan.json: 'pr' is a required property"]


def test_review_violation_is_reported(make_project) -> None:
    """A review missing its verdict is caught, so the sample check is not vacuous."""
    broken = _sample(_REVIEW_SAMPLE)
    del broken["verdict"]
    cfg = _project_cfg(make_project, {"docs/PR_REVIEWS/0002_broken.json": broken})
    violations = [v for v in (_violation(p, "PR_REVIEW.schema.json", cfg) for p in _review_files(cfg)) if v]
    assert len(violations) == 1
    assert violations[0].startswith("0002_broken.json") and "verdict" in violations[0]


def test_review_dir_follows_config(make_project) -> None:
    """``artifacts.reviews`` decides where review artifacts are collected from."""
    root = make_project(config={"artifacts": {"reviews": "reviews"}},
                        files={f"reviews/{_REVIEW_SAMPLE}": _sample(_REVIEW_SAMPLE)})
    cfg = activate(load_config(root))
    assert [p.name for p in _review_files(cfg)] == [_REVIEW_SAMPLE]


def test_sample_review_issues_have_valid_location() -> None:
    """Every sample issue declares a consistent location; the sample covers all three accepted forms."""
    entries = list(_issue_entries(_sample(_REVIEW_SAMPLE)))
    results = [validate_issue_location(e) for e in entries]
    assert [err for err, _dep in results if err] == []
    assert [dep for _err, dep in results] == [False, False, True]


def test_misnamed_review_is_not_collected(make_project) -> None:
    """``is_review_artifact_name`` keeps a 3-digit-prefixed review out of the validated set.

    An empty object would fail PR_REVIEW validation, so collecting it would also surface as a violation.
    """
    cfg = _project_cfg(make_project, {"docs/PR_REVIEWS/916_bad_review.json": {}})
    assert (cfg.path(cfg.artifacts.reviews) / "916_bad_review.json").is_file()
    assert [p.name for p in _review_files(cfg)] == [_REVIEW_SAMPLE]


# ---------------------------------------------------------------------------
# validate_issue_location rule
# ---------------------------------------------------------------------------

def test_validate_issue_location_accepts_file_only() -> None:
    assert validate_issue_location({"file": "x.py"}) == (None, False)


def test_validate_issue_location_accepts_files_only() -> None:
    assert validate_issue_location({"files": ["x.py", "y.py"]}) == (None, False)


def test_validate_issue_location_accepts_both_when_consistent() -> None:
    """Both keys are tolerated only when ``file == files[0]``, flagged as deprecated."""
    err, deprecated = validate_issue_location({"file": "x.py", "files": ["x.py", "y.py"]})
    assert err is None
    assert deprecated is True


def test_validate_issue_location_rejects_both_when_inconsistent() -> None:
    err, _deprecated = validate_issue_location({"file": "a.py", "files": ["b.py"]})
    assert err is not None
    assert "files[0]" in err


def test_validate_issue_location_rejects_neither() -> None:
    err, _deprecated = validate_issue_location({"id": "I1", "title": "noop"})
    assert err is not None
    assert "missing" in err.lower()
