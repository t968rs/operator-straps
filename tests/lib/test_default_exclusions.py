"""Tests for harness_lib.default_exclusions: the seeded ``.claude/review_exclusions.json``."""
import fnmatch
import json
from pathlib import Path
from typing import Callable, List

from harness_lib.config import load_config
from harness_lib.default_exclusions import DEFAULT_EXCLUSIONS, default_patterns, ensure_default_exclusions
from harness_lib.git_status_filter_excluded import configured_exclusions, load_exclusions

_MakeProject = Callable[..., Path]


def _seeded(root: Path) -> List[str]:
    return load_exclusions(root / DEFAULT_EXCLUSIONS)


def test_default_path_is_the_shipped_default(plugin_root: Path) -> None:
    defaults = plugin_root / "config" / "defaults.json"
    assert json.loads(defaults.read_text(encoding="utf-8"))["exclusions"] == DEFAULT_EXCLUSIONS


def test_default_patterns_cover_reviews_summaries_and_harness_rows(make_project: _MakeProject) -> None:
    cfg = load_config(make_project(config={}))
    patterns = default_patterns(cfg)
    assert "docs/PR_REVIEWS/*" in patterns
    assert "docs/PR_SUMMARIES/*" in patterns
    assert "docs/_harness/pr_review_invocation_test_matrix.jsonl" in patterns
    assert "docs/_harness/pr_review_agent_usage.jsonl" in patterns
    assert "docs/_harness/*" not in patterns
    assert DEFAULT_EXCLUSIONS in patterns


def test_default_patterns_follow_configured_artifact_dirs(make_project: _MakeProject) -> None:
    cfg = load_config(make_project(config={
        "artifacts": {"reviews": "ci/reviews/", "summaries": "ci/sums"},
        "matrix_path": "ci/harness/matrix.jsonl", "agent_usage_path": "ci/harness/usage.jsonl"}))
    patterns = default_patterns(cfg)
    assert {"ci/reviews/*", "ci/sums/*", "ci/harness/matrix.jsonl", "ci/harness/usage.jsonl"} <= set(patterns)
    assert "ci/harness/*" not in patterns
    assert "docs/PR_REVIEWS/*" not in patterns


def test_rows_file_in_a_shared_folder_leaves_its_siblings_reviewable(make_project: _MakeProject) -> None:
    cfg = load_config(make_project(config={
        "matrix_path": "docs/test_matrix.jsonl", "agent_usage_path": ".claude/usage.jsonl"}))
    patterns = default_patterns(cfg)
    for sibling in ("docs/guide.md", ".claude/harness.json", ".claude/skills/x/SKILL.md"):
        assert not any(fnmatch.fnmatch(sibling, p) for p in patterns), sibling


def test_root_level_rows_file_is_listed_by_name(make_project: _MakeProject) -> None:
    cfg = load_config(make_project(config={"matrix_path": "matrix.jsonl", "agent_usage_path": "usage.jsonl"}))
    assert {"matrix.jsonl", "usage.jsonl"} <= set(default_patterns(cfg))


def test_default_patterns_cover_the_run_scratch_folder(make_project: _MakeProject) -> None:
    cfg = load_config(make_project(config={}))
    patterns = default_patterns(cfg)
    assert "docs/_scratch/pr_review/*" in patterns
    assert any(fnmatch.fnmatch("docs/_scratch/pr_review/0072/current", p) for p in patterns)
    assert not any(fnmatch.fnmatch("docs/_scratch/notes.md", p) for p in patterns)


def test_scratch_pattern_follows_the_configured_folder(make_project: _MakeProject) -> None:
    cfg = load_config(make_project(config={"artifacts": {"scratch": "tmp/runs/"}}))
    patterns = default_patterns(cfg)
    assert "tmp/runs/*" in patterns
    assert "docs/_scratch/pr_review/*" not in patterns


def test_gitignore_lines_are_not_snapshotted(make_project: _MakeProject) -> None:
    root = make_project(config={}, files={".gitignore": "build/\n*.pyc\n"})
    ensure_default_exclusions(load_config(root))
    patterns = _seeded(root)
    assert not any(p in patterns for p in ("build/*", "*.pyc"))
    assert patterns == default_patterns(load_config(make_project(config={}, name="plain")))


def test_ensure_writes_the_file_when_the_default_is_absent(make_project: _MakeProject) -> None:
    root = make_project(config={})
    written = ensure_default_exclusions(load_config(root))
    assert written == (root / DEFAULT_EXCLUSIONS).resolve()
    patterns = _seeded(root)
    assert any(fnmatch.fnmatch("docs/PR_REVIEWS/0001_x.json", p) for p in patterns)
    assert any(fnmatch.fnmatch("docs/PR_SUMMARIES/0001_x.md", p) for p in patterns)
    assert any(fnmatch.fnmatch("docs/_harness/pr_review_invocation_test_matrix.jsonl", p) for p in patterns)


def test_ensure_works_without_a_harness_json(make_project: _MakeProject) -> None:
    root = make_project()
    assert ensure_default_exclusions(load_config(root)) is not None
    assert (root / DEFAULT_EXCLUSIONS).is_file()


def test_ensure_keeps_an_existing_file(make_project: _MakeProject) -> None:
    mine = {"exclusions": [{"pattern": "only/this/*"}]}
    root = make_project(config={}, files={DEFAULT_EXCLUSIONS: mine})
    assert ensure_default_exclusions(load_config(root)) is None
    assert _seeded(root) == ["only/this/*"]


def test_ensure_skips_a_project_that_disables_exclusions(make_project: _MakeProject) -> None:
    root = make_project(config={"exclusions": None})
    assert ensure_default_exclusions(load_config(root)) is None
    assert not (root / DEFAULT_EXCLUSIONS).exists()


def test_ensure_never_creates_an_explicitly_named_file(make_project: _MakeProject) -> None:
    root = make_project(config={"exclusions": "meta/typo.json"})
    assert ensure_default_exclusions(load_config(root)) is None
    assert not (root / "meta" / "typo.json").exists()
    assert not (root / DEFAULT_EXCLUSIONS).exists()


def test_ensure_returns_none_when_the_folder_is_unwritable(make_project: _MakeProject) -> None:
    root = make_project(files={".claude": "a file where the folder should be"})
    assert ensure_default_exclusions(load_config(root)) is None


def test_configured_exclusions_seeds_the_default(make_project: _MakeProject) -> None:
    root = make_project(config={})
    found = configured_exclusions(root)
    assert found == (root / DEFAULT_EXCLUSIONS).resolve()
    assert found.is_file()


def test_seeded_file_excludes_itself(make_project: _MakeProject) -> None:
    root = make_project(config={})
    ensure_default_exclusions(load_config(root))
    assert any(fnmatch.fnmatch(DEFAULT_EXCLUSIONS, p) for p in _seeded(root))
