"""Canned commit messages for pre-determined change sets (``harness_lib.canned_messages``).

The first entry is the TODO-sync file set; the second is the review-artifact set. A change set takes an
entry's message when every changed file matches one of that entry's patterns.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from harness_lib.branch_commits import BranchCommitDocument
from harness_lib.canned_messages import LOOKUP, get_canned_message, has_canned_message
from harness_lib.commit_txt import entry_from_message, message_problems

TODO_FILES = ["docs/TODO/RepoToDo.json", "docs/TODO/Snapshots/TODO_Snapshot_2026_1023.md"]
REVIEW_FILES = [
    "docs/PR_REVIEWS/0089_1071_sync_gh_issues.json",
    "docs/PR_SUMMARIES/0089_Feat_todo_sync.md",
    "docs/_harness/pr_review_agent_usage.jsonl",
    "docs/_harness/pr_review_invocation_test_matrix.jsonl",
]


def test_the_todo_file_set_has_a_message() -> None:
    changed = ["docs/TODO/_IMPL_TODO.md", "docs/TODO/RepoToDo.json",
               "docs/TODO/ResearchImplementationCatalog.json", *TODO_FILES[1:]]
    assert has_canned_message(changed)
    assert (get_canned_message(changed) or "").startswith("Chore(todo): ")


def test_a_subset_of_an_entry_takes_its_message() -> None:
    message = get_canned_message(["RepoToDo.json"])
    assert message is not None
    assert message.startswith("Chore(todo): ")
    assert message == get_canned_message(TODO_FILES)


def test_a_snapshot_name_matches_by_pattern() -> None:
    assert has_canned_message(["TODO_Snapshot_2031_0101.md"])
    assert not has_canned_message(["TODO_Snapshot.txt"])


def test_paths_normalize_before_matching() -> None:
    assert has_canned_message(["docs\\TODO\\RepoToDo.json", "./docs/TODO/_IMPL_TODO.md"])


def test_paths_normalize_before_a_whole_path_pattern() -> None:
    assert has_canned_message(["./docs/PR_REVIEWS/0001_x.json", "docs\\PR_SUMMARIES\\0001_x.md"])
    assert has_canned_message([".\\docs\\PR_REVIEWS\\0001_x.json"])


def test_any_other_file_voids_the_match() -> None:
    assert get_canned_message([*TODO_FILES, "README.md"]) is None
    assert not has_canned_message(["README.md"])


def test_no_changed_files_has_no_message() -> None:
    assert get_canned_message([]) is None
    assert not has_canned_message([])


def test_the_review_artifact_set_has_a_message() -> None:
    message = get_canned_message(REVIEW_FILES)
    assert (message or "").startswith("Chore(reviews): ")
    assert message != get_canned_message(TODO_FILES)


@pytest.mark.parametrize("path", [
    "src/0001_migration.json",
    "docs/other/0089_notes.json",
    "docs/PR_REVIEWS_old/0089_x.json",
    "notes/pr_review_agent_usage.json",
])
def test_a_lookalike_outside_the_artifact_paths_has_no_message(path: str) -> None:
    assert get_canned_message([path]) is None


def test_files_from_two_entries_do_not_combine() -> None:
    assert get_canned_message([*TODO_FILES, *REVIEW_FILES]) is None


def test_the_lookup_is_read_only() -> None:
    with pytest.raises(TypeError):
        LOOKUP[frozenset({"x.md"})] = "Chore: x"  # type: ignore[index]


@pytest.mark.parametrize("key", list(LOOKUP), ids=lambda key: sorted(key)[0])
def test_every_canned_message_passes_the_message_checks(key: frozenset) -> None:
    entry = entry_from_message(1, ["docs/x.md"], LOOKUP[key])
    document = BranchCommitDocument(branch="b", merge_base="m", commits={1: entry})
    assert message_problems(document) == []


def test_the_patterns_cover_the_plugin_defaults(plugin_root: Path) -> None:
    """A default path or name changed in defaults.json must change the entry that names it."""
    defaults = json.loads((plugin_root / "config" / "defaults.json").read_text(encoding="utf-8"))
    todo, artifacts = defaults["todo"], defaults["artifacts"]
    pattern = todo["snapshots"]["name_pattern"]
    snapshot = re.sub(r"\(\?P<date>[^)]*\)", "2026_1023", pattern).replace("\\.", ".")
    assert re.fullmatch(pattern, snapshot), snapshot
    names = [todo["catalog"], todo["stub_name"], todo["research"]["catalog"], snapshot]
    assert all(has_canned_message([name]) for name in names)
    assert has_canned_message([defaults["matrix_path"], defaults["agent_usage_path"]])
    assert has_canned_message([f"{artifacts['reviews']}/0001_x.json", f"{artifacts['summaries']}/0001_x.md"])
