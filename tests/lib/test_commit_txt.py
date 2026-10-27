"""Behavioral tests for ``harness_lib.commit_txt``: TXT parse and render, message entries and checks."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from harness_lib.branch_commits import BranchCommitDocument, Bucket
from harness_lib.config import activate, load_config
from harness_lib.commit_txt import (
    document_to_txt,
    entry_from_message,
    filler_words,
    message_problems,
    parse_commit_txt,
    quote_problems,
    read_commit_txt,
    vendor_names,
)

_HYPHEN_TXT = """Branch: `9999-demo`
Merge base: abc123
Messaged-through: def456
Split: none - small branch

===

Commit 1 - Runtime+Test (9 files)
"src/demo.py",
"tests/test_demo.py",

Feature(demo): add demo module

Demo module did not exist.

Second paragraph survives.
  - demo.py: new module
---

Commit 2 - Artifact (1 files)
"docs/PR_SUMMARIES/9999_demo.md",

Chore: refresh offline artifacts

Branch: `9999-demo`
"""

_EM_DASH_TXT = """Branch: `9998-legacy`
Merge base: 111aaa

===

Commit 1 — runtime+test (2 files)
"src/legacy.py",
"tests/test_legacy.py",

Fix(legacy): repair legacy module

Branch: `9998-legacy`
"""


@pytest.fixture(autouse=True)
def _default_project(make_project: Callable[..., Path]) -> None:
    """Buckets derive from the plugin defaults (``src/`` runtime, ``tests/`` tests)."""
    activate(load_config(make_project()))


def _document() -> BranchCommitDocument:
    """Build a two-commit document from messages."""
    commits = {
        1: entry_from_message(1, ["src/a.py", "tests/test_a.py"], "Feature(a): add a\n\nWhy.\n  - a.py: new"),
        2: entry_from_message(2, ["docs/PR_REVIEWS/*.json"], "Chore: refresh artifacts"),
    }
    return BranchCommitDocument(branch="9999-demo", merge_base="abc", notes=["Split: none"], commits=commits)


class TestParse:
    def test_header_fields(self) -> None:
        document = parse_commit_txt(_HYPHEN_TXT)
        assert (document.branch, document.merge_base) == ("9999-demo", "abc123")
        assert document.notes == ["Messaged-through: def456", "Split: none - small branch"]

    def test_hyphen_header_buckets(self) -> None:
        document = parse_commit_txt(_HYPHEN_TXT)
        assert document.commits[1].bucket is Bucket.RUNTIME_TEST
        assert document.commits[2].bucket is Bucket.ARTIFACT

    def test_declared_file_count_is_overwritten(self) -> None:
        assert parse_commit_txt(_HYPHEN_TXT).commits[1].file_count == 2

    def test_em_dash_header_parses(self) -> None:
        document = parse_commit_txt(_EM_DASH_TXT)
        assert document.commits[1].bucket is Bucket.RUNTIME_TEST
        assert document.commits[1].files == ["src/legacy.py", "tests/test_legacy.py"]

    def test_message_kept_verbatim_without_footer(self) -> None:
        message = parse_commit_txt(_HYPHEN_TXT).commits[1].message
        assert message == (
            "Feature(demo): add demo module\n\nDemo module did not exist.\n\nSecond paragraph survives.\n"
            "  - demo.py: new module"
        )
        assert parse_commit_txt(_HYPHEN_TXT).commits[2].message == "Chore: refresh offline artifacts"

    def test_read_from_path(self, tmp_path: Path) -> None:
        path = tmp_path / "9999-demo.txt"
        path.write_text(_HYPHEN_TXT, encoding="utf-8")
        assert read_commit_txt(path).branch == "9999-demo"


class TestEntryFromMessage:
    def test_fields(self) -> None:
        entry = entry_from_message(3, ["src/a.py"], "Refactor(a): tidy\n\nWhy.\n\nBranch: `x`\n")
        assert entry.index == 3
        assert entry.bucket is Bucket.RUNTIME
        assert (entry.commit_type, entry.scope, entry.subject) == ("Refactor", "a", "tidy")
        assert entry.header == "Refactor(a): tidy"
        assert entry.message == "Refactor(a): tidy\n\nWhy."

    def test_blank_message_has_null_header(self) -> None:
        assert entry_from_message(1, ["docs/a.md"], "  ").header is None


class TestRender:
    def test_round_trip(self) -> None:
        document = _document()
        parsed = parse_commit_txt(document_to_txt(document))
        for key in (1, 2):
            for field_name in ("bucket", "files", "header", "message"):
                assert getattr(parsed.commits[key], field_name) == getattr(document.commits[key], field_name)
        assert parsed.notes == ["Split: none"]

    def test_commit_header_lines(self) -> None:
        text = document_to_txt(_document())
        assert "\nCommit 1 - Runtime+Test (2 files)\n" in text
        assert "\nCommit 2 - Artifact (1 files)\n" in text

    def test_footer_only_on_last_block(self) -> None:
        text = document_to_txt(_document())
        assert text.count("Branch: `9999-demo`") == 2
        assert text.rstrip().endswith("Chore: refresh artifacts\n\nBranch: `9999-demo`")

    def test_file_lines_quoted_with_trailing_comma(self) -> None:
        assert '\n"src/a.py",\n"tests/test_a.py",\n' in document_to_txt(_document())


class TestMessageProblems:
    def test_clean_document(self) -> None:
        assert message_problems(_document()) == []

    def test_invalid_type(self) -> None:
        document = _document()
        document.commits[1] = entry_from_message(1, ["src/a.py"], "Plan(a): do things")
        assert any("commit 1" in problem for problem in message_problems(document))

    @pytest.mark.parametrize("word", ["Claude", "Copilot", "ChatGPT", "OpenAI", "Anthropic"])
    def test_vendor_name_flagged(self, word: str) -> None:
        document = _document()
        document.commits[1] = entry_from_message(1, ["src/a.py"], f"Fix(a): repair\n\nFound by {word}.")
        assert any(word.lower() in problem.lower() for problem in message_problems(document))

    @pytest.mark.parametrize("prose", [
        "Enhanced x and y.", "improve reliability of the loader", "streamline the flow",
        "more robust parsing", "better maintainability", "comprehensive cleanup", "various fixes",
    ])
    def test_filler_prose_flagged(self, prose: str) -> None:
        document = _document()
        document.commits[1] = entry_from_message(1, ["src/a.py"], f"Fix(a): repair\n\n{prose}")
        assert any("filler" in problem for problem in message_problems(document))

    def test_block_separator_line_flagged(self) -> None:
        document = _document()
        document.commits[1] = entry_from_message(1, ["src/a.py"], "Fix(a): repair\n\nfirst\n---\nsecond")
        assert any("'---'" in problem for problem in message_problems(document))

    def test_double_quote_flagged_with_its_line(self) -> None:
        document = _document()
        message = 'Fix(a): repair\n\nWhy.\n  - a.py: new "Guidance" section'
        document.commits[1] = entry_from_message(1, ["src/a.py"], message)
        problems = [problem for problem in message_problems(document) if "double quote" in problem]
        assert len(problems) == 1
        assert "commit 1" in problems[0] and "line 4" in problems[0]

    def test_double_quote_inside_backticks_still_flagged(self) -> None:
        document = _document()
        document.commits[1] = entry_from_message(1, ["src/a.py"], 'Fix(a): repair\n\nSays `"x"`.')
        assert any("double quote" in problem for problem in message_problems(document))

    def test_single_quote_and_backtick_allowed(self) -> None:
        document = _document()
        document.commits[1] = entry_from_message(1, ["src/a.py"], "Fix(a): repair\n\nIt's the `--` token.")
        assert message_problems(document) == []

    def test_quote_problems_alone_ignore_other_defects(self) -> None:
        document = _document()
        document.commits[1] = entry_from_message(1, ["src/a.py"], 'Plan(a): various "x"')
        assert len(quote_problems(document)) == 1

    def test_filler_word_inside_path_allowed(self) -> None:
        document = _document()
        message = (
            "Fix(a): repair\n\nReader returned None for empty files.\n"
            "  - robust_reader.py: return [] on empty"
        )
        document.commits[1] = entry_from_message(1, ["src/robust_reader.py"], message)
        assert message_problems(document) == []

    def test_vendor_name_inside_path_allowed(self) -> None:
        document = _document()
        message = (
            "Chore(agent): update skill\n\nWhy.\n"
            "  - .claude/skills/x/SKILL.md: edit\n  - CLAUDE.md: edit"
        )
        document.commits[1] = entry_from_message(1, [".claude/skills/x/SKILL.md"], message)
        assert message_problems(document) == []


class TestVendorNames:
    def test_names_outside_paths(self) -> None:
        assert vendor_names("Uses Claude; see .claude/agents/x.md and CLAUDE.md") == ["Claude"]


class TestFillerWords:
    def test_words_outside_paths(self) -> None:
        text = "A robust fix; see docs/improve/notes.md and various tweaks"
        assert filler_words(text) == ["robust", "various"]
