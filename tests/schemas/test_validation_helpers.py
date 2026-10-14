"""Behavioral tests for ``harness_lib.validation.artifact_names`` and
``harness_lib.validation.schema_registry``.

Projects are throwaway repos built by ``make_project``; schema resolution goes through
``schema_path`` (project pinned copy first, else the plugin copy).
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import referencing
import referencing.exceptions

from harness_lib.config import activate, load_config
from harness_lib.validation.artifact_names import (
    SENTINEL_PREFIX,
    is_review_artifact_name,
    phase5_sentinel_dir,
    phase5_sentinel_path,
)
from harness_lib.validation.schema_registry import load_schema, schema_names, schema_registry

_VALID_PLAN = {
    "plan_id": "0001",
    "plan_created": "2026-04-15",
    "execution_model": "serial",
    "pr_attributes": [{"pr": 1, "branch": "feature/x", "base_branch": "main"}],
    "items": [{"id": "TST-1", "title": "t", "action": "noop", "status": "PENDING", "evidence": ""}],
}


def _plan_validator(cfg, registry: referencing.Registry):
    schema = load_schema("ActionPlan.schema.json", cfg)
    return jsonschema.validators.validator_for(schema)(schema, registry=registry)


@pytest.mark.parametrize("name, expected", [
    ("0916_SKILL_pr-review.json", True),
    ("0001_x.json", True),
    ("916_short.json", False),
    ("Catalog.json", False),
    ("BUG_0001.json", False),
    ("", False),
])
def test_is_review_artifact_name(name: str, expected: bool) -> None:
    """Only a 4-digit zero-padded PR number followed by an underscore qualifies."""
    assert is_review_artifact_name(name) is expected


def test_sentinel_dir_follows_default_state_dir(make_project) -> None:
    """Default ``state_dir`` places sentinels under ``.claude/state/harness/pr-review``."""
    cfg = activate(load_config(make_project()))
    assert phase5_sentinel_dir(cfg) == cfg.project_root / ".claude" / "state" / "harness" / "pr-review"


def test_sentinel_dir_follows_configured_state_dir(make_project) -> None:
    """A project ``state_dir`` override moves the sentinel directory with it."""
    cfg = activate(load_config(make_project(config={"state_dir": "var/harness"})))
    assert phase5_sentinel_dir(cfg) == cfg.project_root / "var" / "harness" / "pr-review"


def test_sentinel_path_uses_pr_value_verbatim(make_project) -> None:
    """The sentinel filename is the prefix plus the stringified PR value."""
    cfg = activate(load_config(make_project()))
    assert phase5_sentinel_path(cfg, 42).name == f"{SENTINEL_PREFIX}42"


def test_load_schema_falls_back_to_plugin_copy(make_project, plugin_root: Path) -> None:
    """Without a pinned copy the plugin schema is loaded."""
    cfg = activate(load_config(make_project()))
    plugin_copy = json.loads((plugin_root / "schemas" / "PR_REVIEW.schema.json").read_text(encoding="utf-8"))
    assert load_schema("PR_REVIEW.schema.json", cfg) == plugin_copy


def test_load_schema_prefers_pinned_copy(make_project) -> None:
    """A schema pinned under the project's ``schemas_dir`` wins over the plugin copy."""
    pinned = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "pinned"}
    root = make_project(files={".claude/agent-schemas/PR_REVIEW.schema.json": pinned})
    cfg = activate(load_config(root))
    assert load_schema("PR_REVIEW.schema.json", cfg) == pinned


def test_schema_names_cover_plugin_and_pinned(make_project) -> None:
    """Registry names are the union of plugin schemas and project-pinned extras."""
    root = make_project(files={".claude/agent-schemas/Extra.schema.json": {"type": "object"}})
    cfg = activate(load_config(root))
    names = schema_names(cfg)
    assert {"ActionPlan.schema.json", "prAttributes.schema.json", "PR_REVIEW.schema.json"} <= set(names)
    assert "Extra.schema.json" in names


def test_registry_resolves_action_plan_sibling_ref(make_project) -> None:
    """ActionPlan's bare-filename ``$ref`` to prAttributes resolves through the registry."""
    cfg = activate(load_config(make_project()))
    _plan_validator(cfg, schema_registry(cfg)).validate(_VALID_PLAN)


def test_valid_plan_reaches_the_sibling_ref(make_project) -> None:
    """Non-vacuity guard: without the registry the plan's ``pr_attributes`` ref is unresolvable."""
    cfg = activate(load_config(make_project()))
    with pytest.raises(referencing.exceptions.Unresolvable, match="prAttributes.schema.json"):
        _plan_validator(cfg, referencing.Registry()).validate(_VALID_PLAN)


def test_registry_enforces_sibling_schema_rules(make_project) -> None:
    """A ``pr_attributes`` entry missing its required keys fails through the resolved sibling schema."""
    cfg = activate(load_config(make_project()))
    bad = dict(_VALID_PLAN, pr_attributes=[{"bogus": 1}])
    with pytest.raises(jsonschema.ValidationError, match="'pr' is a required property"):
        _plan_validator(cfg, schema_registry(cfg)).validate(bad)


def test_registry_serves_pinned_sibling(make_project) -> None:
    """A pinned sibling replaces the plugin copy inside the registry."""
    pinned = {"type": "object", "title": "pinned prAttributes"}
    root = make_project(files={".claude/agent-schemas/prAttributes.schema.json": pinned})
    cfg = activate(load_config(root))
    resolved = schema_registry(cfg).contents("prAttributes.schema.json")
    assert resolved == pinned
