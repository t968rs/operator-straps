"""Contract tests for harness_lib.config: defaults, merge rules, validation, typed access."""
from __future__ import annotations

import dataclasses
import json
import re
import sys
from pathlib import Path

import pytest

from conftest import git
from harness_lib.config import ConfigError, activate, active, deactivate, load_config

FPM_SHAPED = {
    "harness_version": "0.1.0",
    "base_branch": "dev",
    "integration_branches": ["dev", "main"],
    "exclusions": "reference/git_curated/machine_generated_exclusions.json",
    "artifacts": {"reviews": "docs/PR_REVIEWS"},
    "tests": {
        "roots": ["scripts/__tests__/"],
        "registry": "scripts/__tests__/__fixtures__/REGISTRY/testRegistry.json",
        "registry_names": ["testRegistry.json", "testRegistry.schema.json"],
    },
    "review": {
        "guard_suite": ["scripts/__tests__/test_runner_modes.py"],
        "registry_guards": ["scripts/__tests__/discipline/registry/test_registry_validation.py"],
        "structural_guard_prefixes": [".github/workflows/"],
        "content_pin_pattern": "_read\\(\"(checks\\.yaml)\"\\)",
        "domain_pointers": [{"prefix": "scripts/fpm/", "pointer": "Apply the arcpy-arch rules."}],
    },
    "commit_buckets": [{"bucket": "Runtime", "prefixes": ["scripts/fpm/"]}],
    "auto_approve_python_c": True,
}


def test_defaults_without_harness_json(make_project) -> None:
    cfg = load_config(make_project())
    assert cfg.source is None
    assert cfg.artifacts.reviews == "docs/PR_REVIEWS"
    assert cfg.tests.registry is None
    assert cfg.review.guard_suite == ()
    assert cfg.auto_approve_python_c is False
    assert [r.bucket for r in cfg.commit_buckets][:2] == ["Artifact", "Planning"]


def test_objects_merge_key_by_key_and_arrays_replace(make_project) -> None:
    root = make_project({"artifacts": {"reviews": "x/reviews"}, "tests": {"roots": ["t/"]}})
    cfg = load_config(root)
    assert cfg.artifacts.reviews == "x/reviews"
    assert cfg.artifacts.plans == "docs/PLANS"
    assert cfg.tests.roots == ("t/",)
    assert cfg.source == root / ".claude" / "harness.json"


def test_fpm_shaped_config_loads(make_project) -> None:
    cfg = load_config(make_project(FPM_SHAPED))
    assert cfg.base_branch == "dev"
    assert cfg.review.domain_pointers[0].prefix == "scripts/fpm/"
    assert cfg.commit_buckets[0].prefixes == ("scripts/fpm/",)
    assert cfg.commit_buckets[0].names == ()
    assert cfg.auto_approve_python_c is True


@pytest.mark.parametrize("bad", [{"unknown_key": 1}, {"artifacts": {"reviews": "/abs"}},
                                 {"commit_buckets": [{"bucket": "Nope"}]}, {"tests": {"file_pattern": "("}},
                                 {"runlogs": {"dir": "/abs/logs"}}, {"runlogs": {"name_pattern": "("}},
                                 {"runlogs": {"folder": "logs"}},
                                 {"runlogs": {"name_pattern": r"run_\d+\.txt"}}])
def test_invalid_config_raises(make_project, bad: dict) -> None:
    with pytest.raises(ConfigError):
        load_config(make_project(bad))


@pytest.mark.parametrize("bad", [{"unknown_key": 1}, {"tests": {"file_pattern": "("}}])
def test_minimal_validation_without_jsonschema(make_project, monkeypatch: pytest.MonkeyPatch,
                                               bad: dict) -> None:
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ConfigError):
        load_config(make_project(bad))


def test_malformed_json_names_the_file(make_project) -> None:
    root = make_project(files={".claude/harness.json": "{not json"})
    with pytest.raises(ConfigError, match="harness.json"):
        load_config(root)


def test_config_is_frozen(make_project) -> None:
    cfg = load_config(make_project())
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.state_dir = "elsewhere"  # type: ignore[misc]


def test_path_is_absolute_under_project(make_project) -> None:
    root = make_project()
    cfg = load_config(root)
    assert cfg.path(cfg.artifacts.reviews) == root / "docs" / "PR_REVIEWS"


def test_is_test_path_uses_roots_or_pattern(make_project) -> None:
    cfg = load_config(make_project({"tests": {"roots": ["scripts/__tests__/"]}}))
    assert cfg.tests.is_test_path("scripts/__tests__/data/x.json")
    assert cfg.tests.is_test_path("pkg/test_thing.py")
    assert cfg.tests.is_test_path("ui/band.test.tsx")
    assert not cfg.tests.is_test_path("pkg/thing.py")


def test_base_branch_configured_wins(make_project) -> None:
    assert load_config(make_project({"base_branch": "dev"})).resolve_base_branch() == "dev"


def test_base_branch_falls_back_to_main_without_remote(make_project) -> None:
    assert load_config(make_project()).resolve_base_branch() == "main"


def test_base_branch_reads_origin_head(make_project, tmp_path: Path) -> None:
    origin = make_project(name="origin")
    git(origin, "branch", "-q", "trunk")
    git(origin, "symbolic-ref", "HEAD", "refs/heads/trunk")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(origin), str(clone))
    assert load_config(clone).resolve_base_branch() == "trunk"


def test_integration_branches_default_and_explicit(make_project) -> None:
    assert load_config(make_project({"base_branch": "dev"})).resolve_integration_branches() == ("dev", "main")
    assert load_config(make_project()).resolve_integration_branches() == ("main",)
    explicit = load_config(make_project({"integration_branches": ["release"]}))
    assert explicit.resolve_integration_branches() == ("release",)


def test_local_test_pattern_default_and_override(make_project) -> None:
    default = load_config(make_project()).review.local_test_pattern
    assert re.search(default, "tests/test_thing_local.py")
    assert not re.search(default, "tests/test_thing.py")
    cfg = load_config(make_project({"review": {"local_test_pattern": "_arc\\.py$"}}))
    assert cfg.review.local_test_pattern == "_arc\\.py$"


def test_fixer_test_deferral_default_and_override(make_project) -> None:
    default = load_config(make_project()).tests
    assert (default.timings, default.fixer_test_seconds, default.defer_flags) == (None, None, ())
    tests = {"timings": "reports/timings.json", "fixer_test_seconds": 90,
             "defer_flags": ["properties.super_slow"]}
    cfg = load_config(make_project({"tests": tests}, name="p2")).tests
    assert (cfg.timings, cfg.fixer_test_seconds, cfg.defer_flags) == (
        "reports/timings.json", 90.0, ("properties.super_slow",))


@pytest.mark.parametrize("bad", [{"fixer_test_seconds": 0}, {"fixer_test_seconds": "60"},
                                 {"timings": "/abs/t.json"}, {"defer_flags": [""]}])
def test_fixer_test_deferral_rejects_bad_values(make_project, bad: dict) -> None:
    with pytest.raises(ConfigError):
        load_config(make_project({"tests": bad}))


def test_runlogs_default_and_override(make_project) -> None:
    default = load_config(make_project()).runlogs
    assert default.dir is None
    assert re.fullmatch(default.name_pattern, "_RUN_TESTS_2026-10-13_120000.txt")["time"] == "120000"
    assert re.fullmatch(default.name_pattern, "_RUN_TESTS_2026-10-13.txt")["date"] == "2026-10-13"
    assert re.fullmatch(default.name_pattern, "_RUN_TESTS_2026-10-13_notes.txt") is None
    override = load_config(make_project({"runlogs": {"dir": "logs/runs"}}, name="p2")).runlogs
    assert override.dir == "logs/runs"
    assert override.name_pattern == default.name_pattern


def test_todo_defaults_leave_the_feature_off(make_project) -> None:
    todo = load_config(make_project()).todo
    assert (todo.catalog, todo.catalog_schema, todo.top_n, todo.inject_context) == (None, None, 10, True)
    assert (todo.snapshots.dir, todo.research.catalog, todo.research.stub_name) == (None, None, None)
    assert re.fullmatch(todo.snapshots.name_pattern, "TODO_Snapshot_2026_1017.md")["date"] == "2026_1017"
    anchor = re.match(todo.research.anchor_pattern, "catalog_entry: docs/R/Catalog.json#alpha-loader")
    assert anchor["id"] == "alpha-loader"
    assert (todo.research.ignore_folders, todo.plans_pairs, todo.gh_repo, todo.gh_max_age_hours) == (
        (), True, None, 24.0)
    assert (todo.rules_disabled, todo.rules_warn_counts) == ((), False)
    assert todo.enabled is False


def test_todo_override_merges_key_by_key(make_project) -> None:
    block = {"catalog": "docs/R/ToDo.json", "top_n": 5, "research": {"catalog": "docs/R/Cat.json",
             "stub_name": "_IMPL_TODO.md", "ignore_folders": ["Old"]}, "gh": {"max_age_hours": 6},
             "rules": {"disabled": ["S6"], "warn_counts": True}, "plans": {"pairs": False}}
    todo = load_config(make_project({"todo": block})).todo
    assert (todo.catalog, todo.top_n, todo.enabled) == ("docs/R/ToDo.json", 5, True)
    assert (todo.research.catalog, todo.research.stub_name, todo.research.ignore_folders) == (
        "docs/R/Cat.json", "_IMPL_TODO.md", ("Old",))
    assert todo.research.anchor_pattern.startswith("^catalog_entry:")
    assert (todo.gh_max_age_hours, todo.rules_disabled, todo.rules_warn_counts, todo.plans_pairs) == (
        6.0, ("S6",), True, False)


@pytest.mark.parametrize("bad", [{"catalog": "/abs/ToDo.json"}, {"top_n": 0}, {"colour": 1},
                                 {"snapshots": {"name_pattern": r"TODO_\d+\.md"}},
                                 {"research": {"anchor_pattern": r"^catalog_entry:\s*\S+$"}},
                                 {"research": {"anchor_pattern": "("}}, {"gh": {"max_age_hours": 0}},
                                 {"rules": {"disabled": ["X1"]}}])
def test_todo_rejects_bad_values(make_project, bad: dict) -> None:
    with pytest.raises(ConfigError):
        load_config(make_project({"todo": bad}))


def test_alternate_config_path_replaces_the_project_file(make_project, tmp_path: Path) -> None:
    root = make_project({"base_branch": "dev"})
    alt = tmp_path / "scratch.json"
    alt.write_text(json.dumps({"todo": {"catalog": "docs/T.json"}}), encoding="utf-8")
    cfg = load_config(root, config_path=alt)
    assert (cfg.source, cfg.project_root) == (alt.resolve(), root.resolve())
    assert cfg.todo.catalog == "docs/T.json" and cfg.base_branch is None


def test_alternate_config_path_must_exist(make_project, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(make_project(), config_path=tmp_path / "missing.json")


def test_worktree_root_default_expands_home_and_repo(make_project, monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    root = make_project(name="widgets")
    expected = tmp_path / ".config" / "superpowers" / "worktrees" / "widgets"
    assert load_config(root).resolve_worktree_root() == expected


def test_worktree_root_configured(make_project, tmp_path: Path) -> None:
    target = (tmp_path / "trees" / "{repo}").as_posix()
    root = make_project({"worktree_root": target}, name="gadgets")
    assert load_config(root).resolve_worktree_root() == tmp_path / "trees" / "gadgets"


def test_worktree_root_from_linked_worktree_names_main_repo(make_project, tmp_path: Path) -> None:
    root = make_project({"worktree_root": (tmp_path / "trees" / "{repo}").as_posix()}, name="gizmo")
    wt = tmp_path / "elsewhere-wt"
    git(root, "worktree", "add", "-q", "--detach", str(wt))
    assert load_config(wt).resolve_worktree_root() == tmp_path / "trees" / "gizmo"


def test_activate_and_active(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    configured = load_config(make_project({"base_branch": "dev"}))
    assert activate(configured) is configured
    assert active() is configured
    deactivate()
    plain = make_project()
    monkeypatch.chdir(plain)
    assert active().project_root == plain.resolve()
    assert active() is active()


def test_defaults_file_validates_against_schema(plugin_root: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((plugin_root / "config" / "harness.schema.json").read_text(encoding="utf-8"))
    defaults = json.loads((plugin_root / "config" / "defaults.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(defaults)
