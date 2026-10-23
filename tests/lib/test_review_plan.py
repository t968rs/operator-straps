"""Behavioral tests for harness_lib.review_plan (pure pr-review planning).

Covers review buckets and their precedence, machine-generated exclusions, the registry auto-merge, the
per-skill-package and coordinated-multi-artifact lens triggers, project lenses merged from the configured
lens file, the Phase 1 structural-guard decision, the roast roll and the reviewer slot plan with the small-PR
lens cut. Every value the planner reads from a project (guard suites, registry names, test roots, skills and
schema directories, exclusions) comes from a throwaway project's ``.claude/harness.json``, activated per test.

Bucketing delegates to ``harness_lib.branch_commits.path_bucket``; the paths used here bucket the same under
any commit-bucket rule set that sends ``.github/workflows/`` to ``Cicd``.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Dict, Optional, Tuple

import pytest

from harness_lib import review_plan as rp
from harness_lib.config import activate, active, load_config
from harness_lib.default_exclusions import default_patterns, ensure_default_exclusions, harness_patterns
from harness_lib.project import plugin_root

_REGISTRY = "tests/registry/registry.json"
_REGISTRY_SCHEMA = "tests/registry/registry.schema.json"
_PATTERNS = ("docs/PR_REVIEWS/*_*.json", "build/offline/summary.json", "*.gitignore")
_GUARD_SUITE = ("tests/guards/test_workflows.py", "tests/guards/test_runner.py")
_LOCAL_GUARD = "tests/guards/test_local_contract.py"
_REGISTRY_GUARDS = ("tests/guards/test_registry.py", "tests/guards/test_registry_targets.py")
_LENS_FILE = "config/lenses.json"
_CONFIG = {
    "skills_dir": "agents/skills/",
    "schemas_dir": "schemas/pinned",
    "exclusions": "config/exclusions.json",
    "tests": {"roots": ["tests/", "qa/"], "registry": _REGISTRY,
              "registry_names": ["registry.json", "registry.schema.json"]},
    "review": {
        "guard_suite": list(_GUARD_SUITE), "local_guards": [_LOCAL_GUARD],
        "registry_guards": list(_REGISTRY_GUARDS),
        "structural_guard_prefixes": [".github/workflows/", "ci/", _REGISTRY_SCHEMA],
        "content_pin_pattern": r'_read\("(checks\.yaml|runner\.py)"\)',
    },
}
_EXCLUSIONS = {"exclusions": [{"pattern": p} for p in _PATTERNS]}


@pytest.fixture(autouse=True)
def project(make_project) -> Path:
    """A throwaway project carrying ``_CONFIG``, activated for every test of the module."""
    root = make_project(config=_CONFIG, files={"config/exclusions.json": _EXCLUSIONS})
    activate(load_config(root))
    return root


def _activate(make_project, config: dict, files: Optional[Dict[str, object]] = None) -> Path:
    """Activate a second project built from ``config`` and ``files``; return its root."""
    root = make_project(config=config, files=files or {}, name="other")
    activate(load_config(root))
    return root


def _buckets(**named: Tuple[str, ...]) -> Dict[str, Tuple[str, ...]]:
    """Builds a full bucket mapping (every key present) from keyword overrides; ``config`` names config."""
    out: Dict[str, Tuple[str, ...]] = {key: () for key in rp.PATH_BUCKETS + ("unbucketed",)}
    for key, paths in named.items():
        out["config-or-registry" if key == "config" else key] = paths
    return out


def _files(prefix: str, count: int) -> Tuple[str, ...]:
    """Returns ``count`` distinct paths under ``prefix``."""
    return tuple(f"{prefix}f{i}.py" for i in range(count))


class TestCatalog:
    """The plugin catalog carries exactly the code-triggered lenses and no project-specific paths."""

    def test_lens_names_match_catalog(self) -> None:
        catalog = json.loads((plugin_root() / "schemas" / "catalogs" / rp.CATALOG_NAME).read_text("utf-8"))
        assert set(rp.LENS_NAMES) == {lens["name"] for lens in catalog["lenses"]}

    def test_catalog_names_no_project_paths(self) -> None:
        text = (plugin_root() / "schemas" / "catalogs" / rp.CATALOG_NAME).read_text("utf-8")
        for literal in ("scripts/__tests__", "scripts/gh_workflows", ".claude/agent-schemas", "REGISTRY/",
                        "PR #"):
            assert literal not in text, literal

    def test_without_project_lenses_is_the_plugin_catalog(self, project: Path) -> None:
        catalog = rp.load_lens_catalog()
        assert [lens["name"] for lens in catalog["lenses"]] == list(rp.LENS_NAMES)
        assert rp.extra_lens_names(catalog) == ()


def _lens_config(lenses: list, default_sub_lenses: list = ()) -> Tuple[dict, dict]:
    """A config naming ``_LENS_FILE`` and the files holding ``lenses``."""
    config = {**_CONFIG, "review": {**_CONFIG["review"], "lenses": _LENS_FILE}}
    body = {"lenses": lenses, "default_sub_lenses": list(default_sub_lenses)}
    return config, {_LENS_FILE: body, "config/exclusions.json": _EXCLUSIONS}


_GEO_LENS = {"name": "geo-boundary", "summary": "s", "scope_template": "Check the geo seam.",
             "trigger": {"description": "two or more geo files", "path_globs": ["src/geo/*"], "min_files": 2}}


class TestProjectLenses:
    """A configured lens file adds path-glob lenses and overrides generic templates by name."""

    def test_project_lens_appended_and_triggered(self, make_project) -> None:
        _activate(make_project, *_lens_config([_GEO_LENS]))
        catalog = rp.load_lens_catalog()
        assert rp.extra_lens_names(catalog) == ("geo-boundary",)
        reviewable = ("src/geo/a.py", "src/geo/b.py", "docs/a.md")
        expected = {"geo-boundary": ("src/geo/a.py", "src/geo/b.py")}
        assert rp.project_lens_paths(catalog, reviewable) == expected

    def test_below_min_files_not_triggered(self, make_project) -> None:
        _activate(make_project, *_lens_config([_GEO_LENS]))
        assert rp.project_lens_paths(rp.load_lens_catalog(), ("src/geo/a.py",)) == {}

    def test_same_name_overrides_template_only(self, make_project) -> None:
        override = {"name": rp.MULTI_ARTIFACT, "scope_template": "Project multi-artifact template."}
        _activate(make_project, *_lens_config([override], [{"name": "extra", "scope_template": "x"}]))
        catalog = rp.load_lens_catalog()
        lens = next(item for item in catalog["lenses"] if item["name"] == rp.MULTI_ARTIFACT)
        assert lens["scope_template"] == "Project multi-artifact template."
        assert "trigger" in lens and rp.extra_lens_names(catalog) == ()
        assert [sub["name"] for sub in catalog["default_sub_lenses"]][-1] == "extra"

    @pytest.mark.parametrize("name", ["docs", "overall", "roast", "system-shape", "Bad_Name", ""])
    def test_bad_or_reserved_name_rejected(self, make_project, name: str) -> None:
        _activate(make_project, *_lens_config([{**_GEO_LENS, "name": name}]))
        with pytest.raises(ValueError):
            rp.load_lens_catalog()

    def test_new_lens_without_globs_rejected(self, make_project) -> None:
        _activate(make_project, *_lens_config([{**_GEO_LENS, "trigger": {"description": "d"}}]))
        with pytest.raises(ValueError, match="path_globs"):
            rp.load_lens_catalog()

    def test_extra_lens_gets_a_slot(self) -> None:
        buckets = _buckets(runtime=("src/geo/a.py", "src/geo/b.py"))
        lenses = {"geo-boundary": ("src/geo/a.py", "src/geo/b.py")}
        slots = rp.slot_plan(buckets, lenses, False, buckets["runtime"], extra_lenses=("geo-boundary",))
        slot = next(s for s in slots if s.lens == "geo-boundary")
        assert slot.id == "geo_boundary" and slot.templates == ("geo-boundary",) and slot.model == "opus"


class TestReviewBucket:
    """One bucket per path; first match wins in cicd > config > tests > runtime > docs."""

    @pytest.mark.parametrize("path, bucket", [
        (".github/workflows/ci.yml", "cicd"),
        ("pyproject.toml", "config-or-registry"),
        ("requirements-dev.txt", "config-or-registry"),
        (".claude/settings.local.json", "config-or-registry"),
        ("schemas/pinned/catalogs/X.json", "config-or-registry"),
        ("src/a.schema.json", "config-or-registry"),
        ("tests/unit/test_a.py", "tests"),
        ("qa/helpers/util.py", "tests"),
        ("src/conftest.py", "tests"),
        ("tools/test_thing.py", "tests"),
        ("web/app.test.ts", "tests"),
        ("web/app.test.js", "tests"),
        ("src/geo/a.py", "runtime"),
        ("web/app.tsx", "runtime"),
        ("tools/run.ps1", "runtime"),
        ("tools/run.sh", "runtime"),
        ("README.md", "docs"),
        ("notes.rst", "docs"),
        ("docs/img/a.png", "docs"),
    ])
    def test_table_rows(self, path: str, bucket: str) -> None:
        assert rp.review_bucket(path) == bucket

    @pytest.mark.parametrize("path, bucket", [
        (_REGISTRY, "config-or-registry"),
        (".claude/agents/pr-reviewer.md", "docs"),
        (".claude/hooks/x.py", "runtime"),
        ("assets/a.lyrx", "unbucketed"),
    ])
    def test_precedence(self, path: str, bucket: str) -> None:
        assert rp.review_bucket(path) == bucket

    def test_unconfigured_root_is_not_a_test_tree(self, make_project) -> None:
        _activate(make_project, {})
        assert rp.review_bucket("qa/helpers/util.py") == "runtime"
        assert rp.review_bucket("schemas/pinned/catalogs/X.json") == "unbucketed"

    def test_sort_buckets_has_every_key_in_input_order(self) -> None:
        out = rp.sort_buckets(["src/b.py", "README.md", "src/a.py", "x.lyrx"])
        assert set(out) == set(rp.PATH_BUCKETS) | {"unbucketed"}
        assert out["runtime"] == ("src/b.py", "src/a.py")
        assert out["docs"] == ("README.md",)
        assert out["unbucketed"] == ("x.lyrx",)
        assert out["cicd"] == ()


class TestExclusions:
    """Exclusion is the configured fnmatch list plus the commit-side ARTIFACT bucket."""

    @pytest.mark.parametrize("path", ["docs/PR_REVIEWS/1558_x.json", "build/offline/summary.json",
                                      "docs/PR_SUMMARIES/1558_x.md", "a/.gitignore"])
    def test_excluded(self, path: str) -> None:
        assert rp.is_excluded(path, _PATTERNS)

    def test_runtime_not_excluded(self) -> None:
        assert not rp.is_excluded("src/a.py", _PATTERNS)

    def test_patterns_load_the_configured_file_then_the_harness_folders(self, project: Path) -> None:
        patterns = rp.exclusion_patterns(project)
        assert patterns[:len(_PATTERNS)] == _PATTERNS
        assert set(harness_patterns(active())) <= set(patterns)
        assert len(patterns) == len(set(patterns))

    def test_null_exclusions_means_no_patterns(self, make_project) -> None:
        root = _activate(make_project, {"exclusions": None})
        assert rp.exclusion_patterns(root) == ()

    def test_default_exclusions_need_the_seeded_file(self, make_project) -> None:
        """A config without ``exclusions`` reads the default file: absent raises, seeded loads it."""
        root = _activate(make_project, {})
        with pytest.raises(FileNotFoundError):
            rp.exclusion_patterns(root)
        assert ensure_default_exclusions(active()) is not None
        assert rp.exclusion_patterns(root) == tuple(default_patterns(active()))


class TestMergeRegistryIntoTests:
    """A registry-only config bucket folds into tests with a recorded rationale."""

    def test_registry_only_merges(self) -> None:
        buckets = _buckets(config=(_REGISTRY, _REGISTRY_SCHEMA), tests=("tests/test_a.py",))
        merged, rationale = rp.merge_registry_into_tests(buckets)
        assert merged["config-or-registry"] == ()
        assert merged["tests"] == ("tests/test_a.py", _REGISTRY, _REGISTRY_SCHEMA)
        assert len(rationale) == 1 and "tests" in rationale[0]

    def test_config_with_other_schema_stays(self) -> None:
        buckets = _buckets(config=(_REGISTRY, "schemas/pinned/PR_REVIEW.schema.json"))
        merged, rationale = rp.merge_registry_into_tests(buckets)
        assert merged == buckets
        assert rationale == ()

    def test_empty_config_is_unchanged(self) -> None:
        merged, rationale = rp.merge_registry_into_tests(_buckets(tests=("tests/test_a.py",)))
        assert merged["tests"] == ("tests/test_a.py",)
        assert rationale == ()

    def test_no_registry_configured_never_merges(self, make_project) -> None:
        _activate(make_project, {})
        buckets = _buckets(config=("pyproject.toml",))
        assert rp.merge_registry_into_tests(buckets) == (buckets, ())


class TestSkillsTouched:
    """Skill names come from ``<skills_dir>/<name>/`` paths only."""

    def test_names_sorted_unique(self) -> None:
        paths = ["agents/skills/pr-sum/SKILL.md", "agents/skills/pr-review/a.md",
                 "agents/skills/pr-review/b/c.json", "agents/skills/README.md", "docs/a.md",
                 ".claude/skills/other/SKILL.md"]
        assert rp.skills_touched(paths) == ("pr-review", "pr-sum")

    def test_skill_folder(self) -> None:
        assert rp.skill_folder("pr-review") == "agents/skills/pr-review/"


class TestSkillMentioned:
    """Whole-name hits outside the skill folder fire; excluded paths never count."""

    def test_hit_outside_folder_fires(self) -> None:
        assert rp.skill_mentioned("pr-review", ["docs/a.md:3:run pr-review now"], _PATTERNS)

    def test_hit_only_inside_folder_does_not(self) -> None:
        lines = ["agents/skills/pr-review/SKILL.md:1:name: pr-review"]
        assert not rp.skill_mentioned("pr-review", lines, _PATTERNS)

    def test_longer_hyphenated_name_does_not(self) -> None:
        assert not rp.skill_mentioned("pr-review", ["docs/a.md:3:see pr-review-watch"], _PATTERNS)

    def test_excluded_path_does_not(self) -> None:
        assert not rp.skill_mentioned("pr-review", ["docs/PR_REVIEWS/1558_x.json:9:pr-review"], _PATTERNS)

    def test_text_colons_are_kept(self) -> None:
        assert rp.skill_mentioned("pr-sum", ["CLAUDE.md:4:Skill: pr-sum: summaries"], _PATTERNS)

    def test_malformed_line_is_ignored(self) -> None:
        assert not rp.skill_mentioned("pr-sum", ["pr-sum"], _PATTERNS)


class TestMultiArtifact:
    """Two or more NEW schema or pinned-schema-directory files trigger the lens."""

    def test_two_new_schemas_fire(self) -> None:
        files = [("A", "a/x.schema.json"), ("A", "schemas/pinned/y.json"), ("A", "src/z.py")]
        assert rp.multi_artifact(files) == ("a/x.schema.json", "schemas/pinned/y.json")

    def test_one_new_one_modified_does_not(self) -> None:
        assert rp.multi_artifact([("A", "a/x.schema.json"), ("M", "b/y.schema.json")]) == ()


class TestGuardDecision:
    """Phase 1 Check 2: configured prefixes, content pins, local tests, registry guards."""

    @pytest.mark.parametrize("path", [".github/workflows/ci.yml", "ci/pipeline.yml"])
    def test_prefix_hit(self, path: str) -> None:
        dec = rp.guard_decision([path, "src/a.py"], [])
        assert dec.applies and not dec.local and not dec.registry
        assert dec.suite == _GUARD_SUITE
        assert any(path in r for r in dec.reasons)

    def test_content_pin(self) -> None:
        dec = rp.guard_decision(["tests/test_x.py"], ["tests/test_x.py"])
        assert dec.applies and dec.suite == _GUARD_SUITE
        assert any("tests/test_x.py" in r for r in dec.reasons)

    def test_local_test_only(self) -> None:
        dec = rp.guard_decision(["tests/geo/test_buffer_local.py"], [])
        assert dec.applies and dec.local and not dec.registry
        assert dec.suite == _GUARD_SUITE + (_LOCAL_GUARD,)

    def test_local_test_pattern_is_configured(self, make_project) -> None:
        review = {**_CONFIG["review"], "local_test_pattern": r"_arcpy\.py$"}
        _activate(make_project, {**_CONFIG, "review": review})
        assert rp.guard_decision(["tests/geo/test_buffer_arcpy.py"], []).local
        assert not rp.guard_decision(["tests/geo/test_buffer_local.py"], []).applies

    def test_registry_touched(self) -> None:
        dec = rp.guard_decision([_REGISTRY], [])
        assert dec.applies and dec.registry
        assert set(_REGISTRY_GUARDS) <= set(dec.suite) and set(_GUARD_SUITE) <= set(dec.suite)
        assert len(dec.suite) == len(set(dec.suite))

    def test_registry_schema_is_a_prefix_and_a_registry_file(self) -> None:
        dec = rp.guard_decision([_REGISTRY_SCHEMA], [])
        assert dec.applies and dec.registry
        assert any(r == f"path prefix: {_REGISTRY_SCHEMA}" for r in dec.reasons)

    def test_none(self) -> None:
        dec = rp.guard_decision(["src/a.py", "docs/a.md"], [])
        assert not dec.applies and dec.suite == () and dec.reasons == ()

    def test_no_guards_configured_never_applies(self, make_project) -> None:
        _activate(make_project, {})
        dec = rp.guard_decision([".github/workflows/ci.yml", "tests/test_x_local.py", _REGISTRY], [])
        assert not dec.applies and dec.suite == ()

    def test_pin_candidate_and_content_pin(self) -> None:
        assert rp.is_pin_candidate("tests/guards/test_x.py")
        assert not rp.is_pin_candidate("src/a.py")
        pin = rp.content_pin()
        assert pin is not None and pin.search('text = _read("checks.yaml")')
        assert not pin.search('_read("other.yaml")')

    def test_no_pin_pattern_means_no_candidates(self, make_project) -> None:
        _activate(make_project, {})
        assert rp.content_pin() is None and not rp.is_pin_candidate("tests/test_x.py")


class TestRollRoast:
    """The roll is a fair coin driven only by the given generator."""

    def test_deterministic_for_a_seed(self) -> None:
        first = [rp.roll_roast(random.Random(0)) for _ in range(3)]
        assert first == [rp.roll_roast(random.Random(0)) for _ in range(3)]

    def test_both_outcomes_occur(self) -> None:
        rng = random.Random(0)
        assert {rp.roll_roast(rng) for _ in range(50)} == {True, False}


class TestSlotPlan:
    """Path-bucket slots, additive lens slots and the small-PR overall/system-shape/roast cut."""

    @staticmethod
    def _small_three_bucket() -> Tuple[Dict[str, Tuple[str, ...]], Tuple[str, ...]]:
        buckets = _buckets(runtime=_files("src/", 2), tests=_files("tests/test_", 2), docs=("docs/a.md",))
        reviewable = buckets["runtime"] + buckets["tests"] + buckets["docs"]
        return buckets, reviewable

    @staticmethod
    def _by_id(slots: Tuple[rp.Slot, ...]) -> Dict[str, rp.Slot]:
        return {slot.id: slot for slot in slots}

    def test_small_pr_folds_system_shape_into_overall(self) -> None:
        buckets, reviewable = self._small_three_bucket()
        slots = self._by_id(rp.slot_plan(buckets, {}, False, reviewable))
        assert "system_shape" not in slots and "roast" not in slots
        assert "overall-system-shape" in slots["overall"].templates
        assert slots["overall"].paths == reviewable

    def test_small_pr_roast_replaces_overall(self) -> None:
        buckets, reviewable = self._small_three_bucket()
        slots = self._by_id(rp.slot_plan(buckets, {}, True, reviewable))
        assert "overall" not in slots and "system_shape" not in slots
        roast = slots["roast"]
        assert roast.roast and roast.lens == "overall" and roast.paths == reviewable
        assert roast.templates == ("overall-system-shape",)

    def test_large_pr_roast_is_additive(self) -> None:
        buckets = _buckets(runtime=_files("src/", 10), tests=_files("tests/test_", 10), docs=("docs/a.md",))
        reviewable = buckets["runtime"] + buckets["tests"] + buckets["docs"]
        slots = self._by_id(rp.slot_plan(buckets, {}, True, reviewable))
        assert {"overall", "system_shape", "roast"} <= set(slots)
        assert slots["overall"].templates == ()
        assert slots["system_shape"].templates == ("overall-system-shape",)
        assert slots["roast"].lens == "roast" and slots["roast"].paths == reviewable

    def test_single_file_bucket_is_sonnet(self) -> None:
        buckets, reviewable = self._small_three_bucket()
        slots = self._by_id(rp.slot_plan(buckets, {}, False, reviewable))
        assert slots["docs"].model == "sonnet"
        assert slots["runtime"].model == "opus" and slots["overall"].model == "opus"

    def test_lens_slots_and_unique_ids(self) -> None:
        buckets = _buckets(config=("a.schema.json", "b.schema.json"), docs=("agents/skills/s/SKILL.md",),
                           unbucketed=("x.lyrx",))
        lenses = {"per-skill-package": ("agents/skills/s/SKILL.md",),
                  "coordinated-multi-artifact": ("a.schema.json", "b.schema.json")}
        slots = rp.slot_plan(buckets, lenses, True, buckets["config-or-registry"] + buckets["docs"])
        ids = [slot.id for slot in slots]
        assert len(ids) == len(set(ids))
        by_id = self._by_id(slots)
        assert by_id["config"].lens == "config-or-registry"
        assert by_id["skill_package"].templates == ("per-skill-package",)
        assert by_id["multi_artifact"].paths == ("a.schema.json", "b.schema.json")
        assert "unbucketed" not in by_id

    def test_unknown_lens_raises(self) -> None:
        buckets, reviewable = self._small_three_bucket()
        with pytest.raises(ValueError, match="no-such-lens"):
            rp.slot_plan(buckets, {"no-such-lens": ("a",)}, False, reviewable)
