"""Behavioral tests for ``harness_lib.commit_grouping``.

Covers capture parsing, pairing, split triggers, grouping and coverage.

Cases run against a floodplain-shaped project (``FPM_CONFIG``) unless a class activates its own.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _commit_helpers import REGISTRY, activate_copy, activate_project, fpm_template  # noqa: E402
from harness_lib.branch_commits import BranchCommitDocument, Bucket  # noqa: E402
from harness_lib.commit_grouping import (  # noqa: E402
    CapturedPath,
    CommitGroup,
    coverage_problems,
    find_pairs,
    fresh_groups,
    merge_capture,
    parse_name_status_z,
    parse_registry_targets,
    plan_commits,
    split_triggers,
)
from harness_lib.commit_txt import entry_from_message  # noqa: E402


@pytest.fixture(scope="module")
def _fpm_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return fpm_template(tmp_path_factory.mktemp("fpm"))


@pytest.fixture(autouse=True)
def _fpm_project(_fpm_template: Path, tmp_path: Path) -> None:
    """Every test starts with a copy of the floodplain-shaped project active."""
    activate_copy(_fpm_template, tmp_path)


def _caps(*paths: str) -> List[CapturedPath]:
    """Build modified-status captures for ``paths``."""
    return [CapturedPath("M", path) for path in paths]


def _document(*groups: List[str]) -> BranchCommitDocument:
    """Build a document with one commit per path list."""
    commits = {n: entry_from_message(n, paths, "Chore: x") for n, paths in enumerate(groups, 1)}
    return BranchCommitDocument(branch="b", merge_base="m", commits=commits, one_path_per_commit=False)


class TestParseNameStatus:
    def test_modify_add_delete_rename(self) -> None:
        text = "M\0a.py\0A\0b.py\0D\0c.py\0R087\0old/d.py\0new/d.py\0"
        assert parse_name_status_z(text) == [
            CapturedPath("M", "a.py"), CapturedPath("A", "b.py"), CapturedPath("D", "c.py"),
            CapturedPath("R", "new/d.py", "old/d.py"),
        ]

    def test_rename_lists_both_paths(self) -> None:
        assert CapturedPath("R", "new/d.py", "old/d.py").paths == ("new/d.py", "old/d.py")

    def test_merge_capture_adds_untracked_and_sorts(self) -> None:
        merged = merge_capture(_caps("z.py"), ["a.py", "z.py"])
        assert merged == [CapturedPath("A", "a.py"), CapturedPath("M", "z.py")]


class TestFindPairs:
    def test_equal_stem(self) -> None:
        pairs = find_pairs(["scripts/fpm/grids/burn.py"], ["scripts/__tests__/grids/test_burn.py"])
        assert pairs == {"scripts/fpm/grids/burn.py": ["scripts/__tests__/grids/test_burn.py"]}

    def test_parent_dir_prefix(self) -> None:
        pairs = find_pairs(["scripts/fpm/_toolbox/fbs/config.py"], ["scripts/__tests__/test_fbs_config.py"])
        assert pairs == {"scripts/fpm/_toolbox/fbs/config.py": ["scripts/__tests__/test_fbs_config.py"]}

    def test_local_suffix_and_shared_dirs_break_ties(self) -> None:
        runtime = ["scripts/fpm/fbs/config.py", "scripts/fpm/regional/config.py"]
        test = "scripts/__tests__/regional/test_config_local.py"
        assert find_pairs(runtime, [test]) == {"scripts/fpm/regional/config.py": [test]}

    def test_unmatched_test_is_left_out(self) -> None:
        assert find_pairs(["scripts/fpm/a.py"], ["scripts/__tests__/test_b.py"]) == {}

    def test_registry_target_pairs_unrelated_name(self) -> None:
        source, test = ".claude/agent_scripts/driver.py", "scripts/__tests__/discipline/test_driver_script.py"
        assert find_pairs([source], [test], {test: [source]}) == {source: [test]}

    def test_registry_target_beats_stem(self) -> None:
        targets = {"scripts/__tests__/test_a.py": ["scripts/fpm/b.py"]}
        pairs = find_pairs(["scripts/fpm/a.py", "scripts/fpm/b.py"], ["scripts/__tests__/test_a.py"], targets)
        assert pairs == {"scripts/fpm/b.py": ["scripts/__tests__/test_a.py"]}

    def test_registry_target_outside_capture_falls_back_to_stem(self) -> None:
        targets = {"scripts/__tests__/test_a.py": ["scripts/fpm/elsewhere.py"]}
        pairs = find_pairs(["scripts/fpm/a.py"], ["scripts/__tests__/test_a.py"], targets)
        assert pairs == {"scripts/fpm/a.py": ["scripts/__tests__/test_a.py"]}

    def test_root_dirs_never_prefix_a_stem(self) -> None:
        assert find_pairs(["scripts/fpm/config.py"], ["scripts/__tests__/test_fpm_config.py"]) == {}


class TestGenericDefaults:
    """Plugin defaults: ``src/`` runtime, ``tests/`` tests, no registry."""

    @pytest.fixture(autouse=True)
    def _defaults(self, make_project: Callable[..., Path]) -> None:
        activate_project(make_project)

    def test_root_dirs_never_prefix_a_stem(self) -> None:
        assert find_pairs(["src/config.py"], ["tests/test_src_config.py"]) == {}

    def test_package_dir_prefixes_a_stem(self) -> None:
        pairs = find_pairs(["src/fbs/config.py"], ["tests/test_fbs_config.py"])
        assert pairs == {"src/fbs/config.py": ["tests/test_fbs_config.py"]}

    def test_pairs_and_docs(self) -> None:
        captures = _caps("src/pkg/a.py", "tests/pkg/test_a.py", "docs/a.md", "pyproject.toml")
        groups, split = plan_commits(captures)
        assert [g.paths for g in groups] == [
            ("src/pkg/a.py", "tests/pkg/test_a.py"), ("pyproject.toml",), ("docs/a.md",),
        ]
        assert split == "none - 1 pairs, one commit"

    def test_registry_named_file_is_not_special(self) -> None:
        groups, _ = plan_commits(_caps("tests/testRegistry.json", "tests/test_a.py"))
        assert [g.paths for g in groups] == [("tests/testRegistry.json", "tests/test_a.py")]


class TestParseRegistryTargets:
    def test_maps_file_to_targets(self) -> None:
        text = (
            '{"tests": [{"file": "scripts/__tests__/test_a.py",'
            ' "properties": {"test_target_paths": ["scripts/fpm/a.py"]}},'
            ' {"file": "scripts/__tests__/test_b.py", "properties": {}}]}'
        )
        assert parse_registry_targets(text) == {"scripts/__tests__/test_a.py": ["scripts/fpm/a.py"]}

    def test_invalid_json_gives_empty(self) -> None:
        assert parse_registry_targets("{not json") == {}


class TestSplitTriggers:
    def test_none_for_single_module(self) -> None:
        pairs = {"scripts/fpm/io/a.py": ["t1"], "scripts/fpm/io/b.py": ["t2"], "scripts/fpm/io/c.py": ["t3"]}
        assert split_triggers(pairs) == []

    def test_cross_module(self) -> None:
        pairs = {"scripts/fpm/io/a.py": ["t1"], "scripts/fpm/fbs/b.py": ["t2"]}
        assert split_triggers(pairs) == ["cross-module (fbs, io)"]

    def test_mixed_intent(self) -> None:
        pairs = {"scripts/fpm/io/fix_a.py": ["t1"], "scripts/fpm/io/b.py": ["t2"]}
        assert split_triggers(pairs) == ["mixed intent (fix_* and feature pairs)"]


class TestPlanCommits:
    def test_fresh_order_and_default_combine(self) -> None:
        captures = _caps(
            "docs/PR_REVIEWS/1_x.json", "docs/a.md", ".claude/x.md", REGISTRY,
            "scripts/fpm/io/a.py", "scripts/__tests__/test_a.py",
            "scripts/fpm/io/b.py", "scripts/__tests__/test_b.py",
            "scripts/fpm/io/solo.py", "pyproject.toml",
        )
        groups, split = plan_commits(captures)
        assert [g.paths for g in groups] == [
            (REGISTRY,),
            ("scripts/fpm/io/a.py", "scripts/__tests__/test_a.py",
             "scripts/fpm/io/b.py", "scripts/__tests__/test_b.py"),
            ("scripts/fpm/io/solo.py",),
            ("pyproject.toml",),
            ("docs/a.md", ".claude/x.md"),
            ("docs/PR_REVIEWS/1_x.json",),
        ]
        assert split.startswith("none")

    def test_split_emits_one_group_per_module(self) -> None:
        captures = _caps("scripts/fpm/io/a.py", "scripts/__tests__/test_a.py",
                         "scripts/fpm/fbs/b.py", "scripts/__tests__/test_b.py",
                         "scripts/fpm/io/c.py", "scripts/__tests__/test_c.py")
        groups, split = plan_commits(captures)
        assert [g.paths for g in groups] == [
            ("scripts/fpm/fbs/b.py", "scripts/__tests__/test_b.py"),
            ("scripts/fpm/io/a.py", "scripts/__tests__/test_a.py",
             "scripts/fpm/io/c.py", "scripts/__tests__/test_c.py"),
        ]
        assert split == "cross-module (fbs, io) - 3 pairs in 2 commits, one per module and intent"

    def test_large_single_module_stays_one_commit(self) -> None:
        paths = [p for n in "abcd"
                 for p in (f"scripts/gh_workflows/{n}.py", f"scripts/__tests__/discipline/test_{n}.py")]
        groups, split = plan_commits(_caps(*paths, *[f"docs/d{i}.md" for i in range(8)]))
        assert len(groups) == 2
        assert split == "none - 4 pairs, one commit"

    def test_mixed_intent_splits_within_module(self) -> None:
        captures = _caps("scripts/fpm/io/fix_a.py", "scripts/__tests__/test_fix_a.py",
                         "scripts/fpm/io/b.py", "scripts/__tests__/test_b.py")
        groups, _ = plan_commits(captures)
        assert [g.paths for g in groups] == [
            ("scripts/fpm/io/b.py", "scripts/__tests__/test_b.py"),
            ("scripts/fpm/io/fix_a.py", "scripts/__tests__/test_fix_a.py"),
        ]

    def test_test_support_file_joins_pair_in_its_directory(self) -> None:
        captures = _caps("scripts/_admin_utils/x.py", "scripts/__tests__/_admin_utils/test_x.py",
                         "scripts/__tests__/_admin_utils/conftest.py")
        groups, _ = plan_commits(captures)
        assert [g.paths for g in groups] == [
            ("scripts/_admin_utils/x.py", "scripts/__tests__/_admin_utils/test_x.py",
             "scripts/__tests__/_admin_utils/conftest.py"),
        ]

    def test_test_support_file_below_pair_directory_joins_pair(self) -> None:
        captures = _caps("scripts/gh_workflows/m.py", "scripts/__tests__/discipline/test_m.py",
                         "scripts/__tests__/discipline/fixtures/m_cases.json")
        groups, _ = plan_commits(captures)
        assert [g.paths for g in groups] == [
            ("scripts/gh_workflows/m.py", "scripts/__tests__/discipline/test_m.py",
             "scripts/__tests__/discipline/fixtures/m_cases.json"),
        ]

    def test_test_support_file_joins_nearest_pair_not_first(self) -> None:
        captures = _caps("scripts/fpm/io/a.py", "scripts/__tests__/test_a.py",
                         "scripts/gh_workflows/m.py", "scripts/__tests__/discipline/test_m.py",
                         "scripts/__tests__/discipline/m_helpers.py",
                         "scripts/__tests__/discipline/fixtures/m_cases.json")
        groups, _ = plan_commits(captures)
        assert [g.paths for g in groups] == [
            ("scripts/fpm/io/a.py", "scripts/__tests__/test_a.py"),
            ("scripts/gh_workflows/m.py", "scripts/__tests__/discipline/test_m.py",
             "scripts/__tests__/discipline/m_helpers.py",
             "scripts/__tests__/discipline/fixtures/m_cases.json"),
        ]

    def test_test_support_file_without_pair_stays_in_test_group(self) -> None:
        captures = _caps("scripts/_admin_utils/x.py", "scripts/__tests__/other/test_x.py",
                         "scripts/__tests__/_admin_utils/conftest.py")
        groups, _ = plan_commits(captures)
        assert groups[-1].paths == ("scripts/__tests__/_admin_utils/conftest.py",)

    def test_registry_targets_drive_pairing(self) -> None:
        captures = _caps(".claude/agent_scripts/driver.py",
                         "scripts/__tests__/discipline/test_driver_script.py")
        targets ={"scripts/__tests__/discipline/test_driver_script.py": [".claude/agent_scripts/driver.py"]}
        groups, _ = plan_commits(captures, registry_targets=targets)
        assert [g.paths for g in groups] == [
            (".claude/agent_scripts/driver.py", "scripts/__tests__/discipline/test_driver_script.py"),
        ]

    def test_non_fpm_sources_pair_with_tests(self) -> None:
        captures = _caps(
            "scripts/__tests__/discipline/test_commit_txt.py", "scripts/gh_workflows/commit_txt.py",
            "scripts/gh_workflows/__init__.py", "pyproject.toml",
        )
        groups, _ = plan_commits(captures)
        assert [g.paths for g in groups] == [
            ("scripts/gh_workflows/commit_txt.py", "scripts/__tests__/discipline/test_commit_txt.py"),
            ("scripts/gh_workflows/__init__.py", "pyproject.toml"),
        ]

    def test_no_split_with_fewer_than_two_pairs(self) -> None:
        _, split = plan_commits(_caps(*[f"docs/d{i}.md" for i in range(13)]))
        assert split == "none - 0 pairs, one commit"

    def test_rename_keeps_both_paths_together(self) -> None:
        groups, _ = plan_commits([CapturedPath("R", "docs/new.md", "docs/old.md")])
        assert [g.paths for g in groups] == [("docs/new.md", "docs/old.md")]

    def test_registry_deferred_when_test_file_deleted(self) -> None:
        captures = [CapturedPath("M", REGISTRY), CapturedPath("D", "scripts/__tests__/test_gone.py")]
        groups, _ = plan_commits(captures)
        assert [g.paths for g in groups] == [("scripts/__tests__/test_gone.py",), (REGISTRY,)]

    def test_existing_grouping_and_message_carried_forward(self) -> None:
        existing = _document(["docs/a.md", "scripts/fpm/io/x.py", "docs/stale.md"])
        existing.commits[1].message = "Feature(io): keep me"
        captures = _caps("docs/a.md", "scripts/fpm/io/x.py", "docs/b.md")
        groups, _ = plan_commits(captures, existing)
        assert groups == [
            CommitGroup(("docs/a.md", "scripts/fpm/io/x.py"), "Feature(io): keep me"),
            CommitGroup(("docs/b.md",), ""),
        ]

    def test_unclaimed_test_joins_preserved_pair_block(self) -> None:
        existing = _document(["scripts/fpm/io/a.py"])
        captures = _caps("scripts/fpm/io/a.py", "scripts/__tests__/test_a.py")
        groups, _ = plan_commits(captures, existing)
        assert [g.paths for g in groups] == [("scripts/fpm/io/a.py", "scripts/__tests__/test_a.py")]

    def test_existing_artifact_glob_claims_matches(self) -> None:
        existing = _document(["docs/PR_REVIEWS/*.json"])
        groups, _ = plan_commits(_caps("docs/PR_REVIEWS/1_x.json", "docs/PR_REVIEWS/2_y.json"), existing)
        assert [g.paths for g in groups] == [("docs/PR_REVIEWS/*.json",)]


PLAN = "docs/superpowers/plans/2026-10-10-x.md"
OFFLINE = ".github/offline/offlineTestReport.json"


class TestFreshGroups:
    def test_planning_paths_form_their_own_bucket_group(self) -> None:
        captures = _caps(".claude/CLAUDE.md", ".claude/skills/x/SKILL.md", PLAN, OFFLINE)
        assert [g.paths for g in fresh_groups(captures)] == [
            (".claude/skills/x/SKILL.md",),
            (".claude/CLAUDE.md", PLAN),
            (OFFLINE,),
        ]


class TestPlanningBinning:
    def test_plan_joins_artifact_group_when_agent_pair_leaves_it_alone(self) -> None:
        captures = _caps(".claude/agent_scripts/driver.py", "scripts/__tests__/discipline/test_driver.py",
                         PLAN, OFFLINE)
        groups, _ = plan_commits(captures)
        assert [g.paths for g in groups] == [
            (".claude/agent_scripts/driver.py", "scripts/__tests__/discipline/test_driver.py"),
            (OFFLINE, PLAN),
        ]

    def test_action_plan_pair_joins_artifact_group(self) -> None:
        captures = _caps("docs/PLANS/1558_ActionPlan.json", "docs/PLANS/1558_PIP.md", OFFLINE)
        groups, _ = plan_commits(captures)
        assert [g.paths for g in groups] == [
            (OFFLINE, "docs/PLANS/1558_ActionPlan.json", "docs/PLANS/1558_PIP.md"),
        ]

    def test_plan_folds_into_docs_before_artifact(self) -> None:
        captures = _caps(PLAN, "docs/conventions/commit_format.md", OFFLINE)
        groups, _ = plan_commits(captures)
        assert [g.paths for g in groups] == [
            ("docs/conventions/commit_format.md", PLAN),
            (OFFLINE,),
        ]

    def test_plan_alone_without_docs_or_artifact_stays(self) -> None:
        captures = _caps(".claude/agent_scripts/driver.py", "scripts/__tests__/discipline/test_driver.py",
                         PLAN)
        groups, _ = plan_commits(captures)
        assert [g.paths for g in groups] == [
            (".claude/agent_scripts/driver.py", "scripts/__tests__/discipline/test_driver.py"),
            (PLAN,),
        ]

    def test_binned_group_lands_last_with_planning_bucket(self) -> None:
        captures = _caps("scripts/fpm/io/a.py", "scripts/__tests__/test_a.py", PLAN, OFFLINE)
        groups, _ = plan_commits(captures)
        assert groups[-1].paths == (OFFLINE, PLAN)
        assert _document(*[list(g.paths) for g in groups]).commits[2].bucket is Bucket.PLANNING

    def test_new_plan_joins_carried_forward_artifact_block(self) -> None:
        existing = _document(["scripts/fpm/io/a.py"], [".github/offline/*Report.json"])
        groups, _ = plan_commits(_caps("scripts/fpm/io/a.py", OFFLINE, PLAN), existing)
        assert [g.paths for g in groups] == [("scripts/fpm/io/a.py",), (".github/offline/*Report.json", PLAN)]

    def test_new_plan_without_artifact_block_keeps_planning_group(self) -> None:
        groups, _ = plan_commits(_caps("scripts/fpm/io/a.py", PLAN), _document(["scripts/fpm/io/a.py"]))
        assert [g.paths for g in groups] == [("scripts/fpm/io/a.py",), (PLAN,)]

    def test_plan_with_claude_md_stays_planning(self) -> None:
        groups, _ = plan_commits(_caps(".claude/CLAUDE.md", "docs/a.md", PLAN, OFFLINE))
        assert [g.paths for g in groups] == [("docs/a.md",), (".claude/CLAUDE.md", PLAN), (OFFLINE,)]


SKILL_DOCS = (".claude/agents/messenger.md", ".claude/skills/pr-sum-viz/SKILL.md",
              ".claude/skills/pr-sum/SKILL.md")
LOCAL_PLAN = "docs/superpowers/plans/2026-10-10-pr-sum-local-capture.md"
DESIGN = "docs/RESEARCH/skills/pr_sum/DesignEvolution.json"
FRESH_DOC_TAIL = (".claude/CLAUDE.md", ".claude/skills/branch-commit-msg/txt_format.md",
                  ".claude/skills/pr-sum-alt/SKILL.md", DESIGN)
PAIR = ("scripts/gh_workflows/commit_grouping.py", "scripts/__tests__/discipline/test_commit_grouping.py")


class TestDocConsolidation:
    def test_branch_doc_tail_gives_one_docs_and_one_planning_group(self) -> None:
        existing = _document(list(PAIR), [LOCAL_PLAN], list(SKILL_DOCS))
        captures = _caps(*FRESH_DOC_TAIL, *SKILL_DOCS, OFFLINE, *PAIR, LOCAL_PLAN)
        groups, _ = plan_commits(captures, existing)
        assert groups == [
            CommitGroup(PAIR, "Chore: x"),
            CommitGroup((*SKILL_DOCS, ".claude/skills/branch-commit-msg/txt_format.md",
                         ".claude/skills/pr-sum-alt/SKILL.md"), ""),
            CommitGroup((LOCAL_PLAN, ".claude/CLAUDE.md", DESIGN), ""),
            CommitGroup((OFFLINE,), ""),
        ]

    def test_carried_mixed_docs_planning_block_splits_by_bucket(self) -> None:
        existing = _document([".claude/CLAUDE.md"], [LOCAL_PLAN], list(SKILL_DOCS), list(FRESH_DOC_TAIL[1:]))
        groups, _ = plan_commits(_caps(*FRESH_DOC_TAIL, *SKILL_DOCS, LOCAL_PLAN), existing)
        assert [g.paths for g in groups] == [
            (*SKILL_DOCS, *FRESH_DOC_TAIL[1:3]),
            (".claude/CLAUDE.md", LOCAL_PLAN, DESIGN),
        ]

    def test_single_source_keeps_message(self) -> None:
        existing = _document(list(SKILL_DOCS), [".claude/CLAUDE.md", DESIGN])
        existing.commits[1].message = "Docs(skills): keep me"
        existing.commits[2].message = "Docs(planning): keep me too"
        groups, _ = plan_commits(_caps(*SKILL_DOCS, ".claude/CLAUDE.md", DESIGN), existing)
        assert [g.message for g in groups] == ["Docs(skills): keep me", "Docs(planning): keep me too"]

    def test_merged_sources_clear_message(self) -> None:
        existing = _document([SKILL_DOCS[0]])
        existing.commits[1].message = "Docs(agents): stale"
        groups, _ = plan_commits(_caps(*SKILL_DOCS), existing)
        assert groups == [CommitGroup(SKILL_DOCS, "")]

    def test_mixed_groups_untouched(self) -> None:
        existing = _document(["docs/a.md", "scripts/fpm/io/x.py"], [OFFLINE, "docs/b.md"])
        groups, _ = plan_commits(_caps("docs/a.md", "scripts/fpm/io/x.py", OFFLINE, "docs/b.md", "docs/c.md"),
                                 existing)
        assert [g.paths for g in groups] == [
            ("docs/a.md", "scripts/fpm/io/x.py"), (OFFLINE, "docs/b.md"), ("docs/c.md",),
        ]

    def test_rename_sides_stay_together_across_buckets(self) -> None:
        captures = [CapturedPath("R", "docs/a.md", "docs/superpowers/plans/old.md"), CapturedPath("M", PLAN)]
        groups, _ = plan_commits(captures)
        assert [g.paths for g in groups] == [("docs/a.md", "docs/superpowers/plans/old.md", PLAN)]


class TestCoverageProblems:
    def test_artifact_glob_with_planning_doc_is_clean(self) -> None:
        document = _document([".github/offline/*Report.json", PLAN])
        assert document.commits[1].bucket is Bucket.PLANNING
        assert coverage_problems(document, _caps(OFFLINE, PLAN)) == []

    def test_glob_in_planning_only_block_is_rejected(self) -> None:
        document = _document(["docs/superpowers/plans/*.md"])
        assert any("glob" in problem for problem in coverage_problems(document, _caps(PLAN)))

    def test_complete(self) -> None:
        document = _document(["a.py"], ["docs/PR_REVIEWS/*.json"])
        assert coverage_problems(document, _caps("a.py", "docs/PR_REVIEWS/1.json")) == []

    def test_missing_path(self) -> None:
        problems = coverage_problems(_document(["a.py"]), _caps("a.py", "b.py"))
        assert problems == ["'b.py' is in no commit"]

    def test_stale_path(self) -> None:
        problems = coverage_problems(_document(["a.py", "gone.py"]), _caps("a.py"))
        assert any("gone.py" in problem for problem in problems)

    def test_glob_outside_artifact(self) -> None:
        document = _document(["docs/*.md"])
        assert document.commits[1].bucket is Bucket.DOCS
        assert any("glob" in problem for problem in coverage_problems(document, _caps("docs/a.md")))

    def test_glob_overlapping_literal(self) -> None:
        document = _document(["docs/PR_REVIEWS/1.json"], ["docs/PR_REVIEWS/*.json"])
        problems = coverage_problems(document, _caps("docs/PR_REVIEWS/1.json"))
        assert any("commit 1 and commit 2" in problem for problem in problems)
