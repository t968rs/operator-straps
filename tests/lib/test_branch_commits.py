"""Behavioral tests for ``harness_lib.branch_commits``.

Covers Bucket parsing, path bucketing and BranchCommitDocument validation.

Path-bucket cases run against a floodplain-shaped project (``FPM_CONFIG``) unless a class activates its own.
"""
from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path
from typing import Callable, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _commit_helpers import REGISTRY, activate_copy, activate_project, fpm_template  # noqa: E402
from harness_lib.branch_commits import (  # noqa: E402
    BUCKET_ORDER,
    BranchCommitDocument,
    Bucket,
    CommitEntry,
    commit_bucket,
    is_planning_path,
    is_registry_path,
    is_source_path,
    path_bucket,
)


@pytest.fixture(scope="module")
def _fpm_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return fpm_template(tmp_path_factory.mktemp("fpm"))


@pytest.fixture(autouse=True)
def _fpm_project(_fpm_template: Path, tmp_path: Path) -> None:
    """Every test starts with a copy of the floodplain-shaped project active."""
    activate_copy(_fpm_template, tmp_path)


def _commit(index: int, bucket: str, files: List[str], header: Optional[str] = "Chore: x") -> CommitEntry:
    """Build a minimal commit entry."""
    return CommitEntry(index=index, bucket=bucket, files=files, header=header)


def _one_test_commit_document() -> BranchCommitDocument:
    """A document holding one Test commit for ``a.py``."""
    return BranchCommitDocument(branch="demo", merge_base="abc", commits={1: _commit(1, "Test", ["a.py"])})


class TestCommitEntry:
    def test_declared_fields(self) -> None:
        assert [f.name for f in fields(CommitEntry)] == [
            "index", "bucket", "files", "header", "message", "commit_type", "scope", "subject",
            "tag", "body", "bullets", "branch", "file_count",
        ]

    def test_defaults(self) -> None:
        entry = CommitEntry(index=1, bucket=Bucket.DOCS)
        fields = (entry.files, entry.header, entry.message, entry.bullets, entry.file_count)
        assert fields == ([], None, "", [], 0)

    def test_list_defaults_are_not_shared(self) -> None:
        first, second = CommitEntry(index=1, bucket=Bucket.DOCS), CommitEntry(index=2, bucket=Bucket.DOCS)
        first.files.append("a.md")
        assert second.files == []


class TestBucket:
    def test_canonical_value(self) -> None:
        assert Bucket("Runtime+Test") is Bucket.RUNTIME_TEST

    def test_legacy_lowercase_and_whitespace(self) -> None:
        assert Bucket(" runtime+test ") is Bucket.RUNTIME_TEST
        assert Bucket("docs") is Bucket.DOCS

    def test_unknown_label_raises(self) -> None:
        with pytest.raises(ValueError):
            Bucket("runtime + other")

    def test_is_str(self) -> None:
        assert Bucket.CICD == "Cicd"

    def test_order_matches_step5(self) -> None:
        assert BUCKET_ORDER == (
            Bucket.RUNTIME_TEST, Bucket.RUNTIME, Bucket.TEST, Bucket.CICD,
            Bucket.AGENT, Bucket.OTHER, Bucket.DOCS, Bucket.PLANNING, Bucket.ARTIFACT,
        )

    def test_planning_label(self) -> None:
        assert Bucket("planning") is Bucket.PLANNING
        assert Bucket.PLANNING == "Planning"


class TestPathBucket:
    @pytest.mark.parametrize(("path", "expected"), [
        (".claude/skills/branch-commit-msg/SKILL.md", Bucket.DOCS),
        (".claude/skills/branch-commit-msg/txt_format.md", Bucket.DOCS),
        (".claude/agents/pr-team-fixer.md", Bucket.DOCS),
        (".claude/CLAUDE.md", Bucket.PLANNING),
        (".claude/agent_scripts/branch_commit_msg.py", Bucket.AGENT),
        (".claude/settings.json", Bucket.AGENT),
        ("CLAUDE.md", Bucket.PLANNING),
        ("docs/superpowers/plans/x.md", Bucket.PLANNING),
        ("docs/superpowers/specs/y.md", Bucket.PLANNING),
        ("docs/PLANS/1558_ActionPlan.json", Bucket.PLANNING),
        ("docs/RESEARCH/skills/pr_sum/DesignEvolution.json", Bucket.PLANNING),
        ("docs/RESEARCH/skills/pr_sum/notes.md", Bucket.DOCS),
        ("docs/PR_REVIEWS/1537_0093_gdb.json", Bucket.ARTIFACT),
        ("docs/PR_SUMMARIES/1537_x.md", Bucket.ARTIFACT),
        (".github/offline/offlineTestReport.json", Bucket.ARTIFACT),
        (".github/offline/summary.json", Bucket.ARTIFACT),
        (".claude/skills/pr-review/invocation_test_matrix.jsonl", Bucket.ARTIFACT),
        (".claude/skills/pr-review/*matrix.jsonl", Bucket.ARTIFACT),
        (".github/workflows/checks.yaml", Bucket.CICD),
        ("scripts/__tests__/workflows/scripts/check_runner.py", Bucket.CICD),
        ("scripts/__tests__/shared/summary_builder.py", Bucket.CICD),
        ("test_env.txt", Bucket.CICD),
        ("scripts/__tests__/test_fbs_config.py", Bucket.TEST),
        ("scripts/__tests__/__fixtures__/REGISTRY/testRegistry.json", Bucket.TEST),
        ("scripts/fpm/_toolbox/fbs/config.py", Bucket.RUNTIME),
        ("docs/conventions/commit_format.md", Bucket.DOCS),
        ("README.md", Bucket.DOCS),
        ("notes.txt", Bucket.DOCS),
        ("scripts/_admin_utils/txt_to_commit_dict.py", Bucket.OTHER),
        ("pyproject.toml", Bucket.OTHER),
    ])
    def test_first_match(self, path: str, expected: Bucket) -> None:
        assert path_bucket(path) is expected

    @pytest.mark.parametrize(("path", "expected"), [
        ("scripts/fpm/io/a.py", True),
        ("scripts/gh_workflows/commit_txt.py", True),
        (".claude/agent_scripts/branch_commit_msg.py", True),
        ("scripts/__tests__/test_a.py", False),
        ("scripts/__tests__/workflows/scripts/check_runner.py", False),
        ("scripts/fpm/io/data.json", False),
        ("docs/a.md", False),
    ])
    def test_source_detection(self, path: str, expected: bool) -> None:
        assert is_source_path(path) is expected

    @pytest.mark.parametrize(("path", "expected"), [
        ("docs/superpowers/plans/2026-10-10-x.md", True),
        ("docs/superpowers/specs/y.md", True),
        ("docs/PLANS/1558_ActionPlan.json", True),
        ("docs/PLANS/1558_PIP.md", True),
        ("docs/conventions/commit_format.md", False),
        ("docs/PR_REVIEWS/1558_x.json", False),
        (".claude/skills/pr-sum/SKILL.md", False),
    ])
    def test_planning_detection(self, path: str, expected: bool) -> None:
        assert is_planning_path(path) is expected

    def test_registry_detection(self) -> None:
        assert is_registry_path(REGISTRY)
        assert not is_registry_path("scripts/__tests__/test_fbs_config.py")

    def test_registry_matches_configured_path_only(self) -> None:
        assert not is_registry_path("elsewhere/testRegistry.json")


class TestGenericDefaults:
    """Plugin defaults: ``src/`` runtime, ``tests/`` tests, no registry."""

    @pytest.fixture(autouse=True)
    def _defaults(self, make_project: Callable[..., Path]) -> None:
        activate_project(make_project)

    @pytest.mark.parametrize(("path", "expected"), [
        ("src/pkg/mod.py", Bucket.RUNTIME),
        ("tests/test_mod.py", Bucket.TEST),
        (".github/workflows/ci.yaml", Bucket.CICD),
        (".claude/settings.json", Bucket.AGENT),
        (".claude/skills/x/SKILL.md", Bucket.DOCS),
        ("CLAUDE.md", Bucket.PLANNING),
        ("docs/superpowers/plans/x.md", Bucket.PLANNING),
        ("docs/PR_REVIEWS/1_x.json", Bucket.ARTIFACT),
        ("docs/guide.md", Bucket.DOCS),
        ("README.md", Bucket.DOCS),
        ("scripts/fpm/a.py", Bucket.OTHER),
        ("scripts/__tests__/test_a.py", Bucket.OTHER),
        ("pyproject.toml", Bucket.OTHER),
    ])
    def test_default_buckets(self, path: str, expected: Bucket) -> None:
        assert path_bucket(path) is expected

    def test_no_registry_configured(self) -> None:
        assert not is_registry_path("scripts/__tests__/__fixtures__/REGISTRY/testRegistry.json")
        assert not is_registry_path("tests/testRegistry.json")

    def test_source_and_test_combine(self) -> None:
        assert commit_bucket(["src/pkg/mod.py", "tests/test_mod.py"]) is Bucket.RUNTIME_TEST


class TestConfiguredRules:
    def test_registry_names_bucket_as_test(self, make_project: Callable[..., Path]) -> None:
        activate_project(make_project, {"tests": {"registry_names": ["registry.json"]}})
        assert is_registry_path("anywhere/registry.json")
        assert path_bucket("anywhere/registry.json") is Bucket.TEST

    def test_registry_path_outside_test_root_buckets_as_test(self, make_project: Callable[..., Path]) -> None:
        activate_project(make_project, {"tests": {"registry": "meta/registry.json"}})
        assert path_bucket("meta/registry.json") is Bucket.TEST

    def test_first_matching_rule_wins(self, make_project: Callable[..., Path]) -> None:
        rules = [{"bucket": "Cicd", "prefixes": ["lib/ci/"]}, {"bucket": "Runtime", "prefixes": ["lib/"]}]
        activate_project(make_project, {"commit_buckets": rules})
        assert (path_bucket("lib/ci/run.py"), path_bucket("lib/core.py")) == (Bucket.CICD, Bucket.RUNTIME)

    def test_planning_prefixes_come_from_artifacts(self, make_project: Callable[..., Path]) -> None:
        activate_project(make_project, {"artifacts": {"planning_prefixes": ["plans/"]}})
        assert is_planning_path("plans/x.md")
        assert not is_planning_path("docs/superpowers/plans/x.md")


class TestCommitBucket:
    def test_runtime_and_test_combine(self) -> None:
        paths = ["scripts/fpm/a.py", "scripts/__tests__/test_a.py"]
        assert commit_bucket(paths) is Bucket.RUNTIME_TEST

    def test_single_bucket(self) -> None:
        assert commit_bucket(["docs/a.md", "README.md"]) is Bucket.DOCS

    def test_mixed_takes_highest_rank(self) -> None:
        assert commit_bucket(["docs/a.md", "scripts/fpm/a.py"]) is Bucket.RUNTIME

    def test_runtime_test_outranks_mix(self) -> None:
        paths = [".claude/x.md", "scripts/fpm/a.py", "scripts/__tests__/test_a.py"]
        assert commit_bucket(paths) is Bucket.RUNTIME_TEST

    def test_non_fpm_source_and_test_combine(self) -> None:
        paths = ["scripts/gh_workflows/commit_txt.py", "scripts/__tests__/discipline/test_commit_txt.py"]
        assert commit_bucket(paths) is Bucket.RUNTIME_TEST

    def test_agent_script_and_test_combine(self) -> None:
        paths = [".claude/agent_scripts/x.py", "scripts/__tests__/discipline/test_x.py"]
        assert commit_bucket(paths) is Bucket.RUNTIME_TEST

    def test_non_python_other_and_test_stay_test(self) -> None:
        assert commit_bucket(["pyproject.toml", "scripts/__tests__/test_a.py"]) is Bucket.TEST

    def test_artifact_with_planning_doc_is_planning(self) -> None:
        paths = [".github/offline/offlineTestReport.json", "docs/superpowers/plans/x.md"]
        assert commit_bucket(paths) is Bucket.PLANNING

    def test_docs_with_planning_doc_is_docs(self) -> None:
        paths = [".claude/skills/pr-sum/SKILL.md", "docs/superpowers/plans/x.md"]
        assert commit_bucket(paths) is Bucket.DOCS

    def test_agent_script_with_claude_md_is_agent(self) -> None:
        assert commit_bucket([".claude/agent_scripts/x.py", ".claude/CLAUDE.md"]) is Bucket.AGENT

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            commit_bucket([])


class TestBranchCommitDocumentConstruction:
    def test_partial_construction_skips_null_check(self) -> None:
        document = BranchCommitDocument()
        assert document.branch is None
        assert document.commits == {}

    def test_post_init_coerces_bucket(self) -> None:
        document = BranchCommitDocument(commits={1: _commit(1, "test", ["a.py"])})
        assert document.commits[1].bucket is Bucket.TEST

    def test_post_init_overwrites_file_count(self) -> None:
        document = BranchCommitDocument(commits={1: _commit(1, "Test", ["a.py", "b.py"])})
        assert document.commits[1].file_count == 2

    def test_post_init_rejects_unknown_bucket(self) -> None:
        with pytest.raises(ValueError, match="bucket"):
            BranchCommitDocument(commits={1: _commit(1, "release", ["a.py"])})

    def test_post_init_rejects_shared_path_by_default(self) -> None:
        commits = {1: _commit(1, "Test", ["a.py"]), 2: _commit(2, "Docs", ["a.py"])}
        with pytest.raises(ValueError, match="a.py"):
            BranchCommitDocument(commits=commits)

    def test_strategy_field_allows_shared_path(self) -> None:
        commits = {1: _commit(1, "Test", ["a.py"]), 2: _commit(2, "Docs", ["a.py"])}
        document = BranchCommitDocument(commits=commits, one_path_per_commit=False)
        assert len(document.commits) == 2

    def test_pending_defaults_false(self) -> None:
        assert BranchCommitDocument().pending is False

    def test_pending_allows_one_commit(self) -> None:
        document = BranchCommitDocument(commits={1: _commit(1, "Test", ["a.py"])}, pending=True)
        assert document.pending is True

    def test_pending_rejects_second_commit(self) -> None:
        commits = {1: _commit(1, "Test", ["a.py"]), 2: _commit(2, "Docs", ["b.md"])}
        with pytest.raises(ValueError, match="pending document has 2 commits"):
            BranchCommitDocument(commits=commits, pending=True)


class TestBranchCommitDocumentValidate:
    def test_null_branch_raises(self) -> None:
        document = BranchCommitDocument(merge_base="abc")
        with pytest.raises(ValueError, match="branch"):
            document.validate()

    def test_null_merge_base_raises(self) -> None:
        document = BranchCommitDocument(branch="demo")
        with pytest.raises(ValueError, match="merge_base"):
            document.validate()

    def test_null_commit_header_raises(self) -> None:
        commits = {1: _commit(1, "Test", ["a.py"], header=None)}
        document = BranchCommitDocument(branch="demo", merge_base="abc", commits=commits)
        with pytest.raises(ValueError, match="header"):
            document.validate()

    def test_validate_null_false_skips_null_check(self) -> None:
        BranchCommitDocument().validate(validate_null=False)

    def test_complete_document_passes(self) -> None:
        commits = {1: _commit(1, "Test", ["a.py"])}
        document = BranchCommitDocument(branch="demo", merge_base="abc", commits=commits)
        assert document.validate() is document

    def test_mutation_then_validate_catches_shared_path(self) -> None:
        document = _one_test_commit_document()
        document.commits[2] = _commit(2, "Docs", ["a.py"])
        with pytest.raises(ValueError, match="a.py"):
            document.validate()

    def test_argument_overrides_strategy_field(self) -> None:
        document = _one_test_commit_document()
        document.commits[2] = _commit(2, "Docs", ["a.py"])
        document.validate(one_path_per_commit=False)

    def test_mutation_then_validate_recounts_files(self) -> None:
        document = BranchCommitDocument(commits={1: _commit(1, "Test", ["a.py"])})
        document.commits[1].files.append("b.py")
        document.validate(validate_null=False)
        assert document.commits[1].file_count == 2
