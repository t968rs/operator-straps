"""``harness_lib.pr_title``: the PR title check merge-commit-msg and pr-sum share, and the ``gh`` retitle.

``title_defect`` names why a title cannot head a commit subject; ``title_problem`` wraps it with the PR and
the two ways out; ``change_pr_title`` refuses a new title with a defect and otherwise runs
``gh pr edit N --title``, the one outside call (``subprocess.run``, swapped here).
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from harness_lib import pr_title

HEAD = "1142-auto-title-pr"


class TestTitleDefect:
    @pytest.mark.parametrize("title", [
        "Feature(harness): pr-sum comparison flows", "Fix: `pydantic` 2.1 floor", "Docs(x):  spaced",
    ])
    def test_conventional_titles_pass(self, title: str) -> None:
        assert pr_title.title_defect(title, HEAD, conventional=True) is None

    def test_a_loose_title_passes_without_the_conventional_rule(self) -> None:
        assert pr_title.title_defect("`pr sum` levels update", HEAD) is None

    @pytest.mark.parametrize("title, word", [
        ("`pr sum` levels update", "Word(scope): summary"),
        ("Fix(workers):", "Word(scope): summary"),
        ("Fix(x): pool — crash", "non-ASCII"),
        ("1142 auto title pr", "branch name"),
        ("Fix(x): one\nFix(x): two", "one line"),
        ("   ", "empty"),
    ])
    def test_defects_are_named(self, title: str, word: str) -> None:
        defect = pr_title.title_defect(title, HEAD, conventional=True)
        assert defect is not None and word in defect, defect

    def test_branch_name_rule_needs_a_separator_in_the_head(self) -> None:
        assert pr_title.title_defect("main", "main") is None


class TestTitleProblem:
    def test_problem_names_the_pr_and_both_ways_out(self) -> None:
        problem = pr_title.title_problem(240, "`pr sum` levels update", HEAD, conventional=True)
        assert problem is not None
        assert problem.startswith("PR #240 title '`pr sum` levels update' ")
        assert "Conventional-Commit" in problem
        assert "gh pr edit 240 --title" in problem and "--auto-title" in problem

    def test_no_problem_for_a_usable_title(self) -> None:
        assert pr_title.title_problem(240, "Feature(harness): x", HEAD, conventional=True) is None


class _Done:
    def __init__(self, code: int = 0, err: str = "") -> None:
        self.returncode, self.stdout, self.stderr = code, "", err


class TestChangePrTitle:
    def test_runs_gh_pr_edit_in_the_repo(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        calls: List[tuple] = []
        monkeypatch.setattr(pr_title.subprocess, "run",
                            lambda argv, **kw: calls.append((argv, kw.get("cwd"))) or _Done())
        pr_title.change_pr_title(240, "Feature(harness): x", tmp_path, HEAD)
        assert calls == [(["gh", "pr", "edit", "240", "--title", "Feature(harness): x"], tmp_path)]

    def test_refuses_a_title_with_a_defect_before_gh(self, monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
        monkeypatch.setattr(pr_title.subprocess, "run", lambda *a, **k: pytest.fail("gh ran"))
        with pytest.raises(pr_title.TitleError, match=r"new title '`pr sum` update' .*Word\(scope\)"):
            pr_title.change_pr_title(240, "`pr sum` update", tmp_path, HEAD)

    def test_gh_failure_is_a_title_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(pr_title.subprocess, "run", lambda *a, **k: _Done(1, "HTTP 403"))
        with pytest.raises(pr_title.TitleError, match="gh pr edit 240 failed: HTTP 403"):
            pr_title.change_pr_title(240, "Feature(harness): x", tmp_path, HEAD)

    def test_missing_gh_is_a_title_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        def missing(*_a, **_k):
            raise FileNotFoundError("gh")
        monkeypatch.setattr(pr_title.subprocess, "run", missing)
        with pytest.raises(pr_title.TitleError, match="gh is not installed"):
            pr_title.change_pr_title(240, "Feature(harness): x", tmp_path, HEAD)
