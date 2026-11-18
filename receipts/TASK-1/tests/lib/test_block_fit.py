"""Tests for the block read of the commit drivers: one batched ``git diff`` and a fit before any cut.

``branch_capture.path_diffs`` reads a block's tracked paths with one ``git diff`` per pathspec chunk and must
return, per path, what ``path_diff`` returns for that path alone. ``commit_diff.fit_sections`` keeps a block
under its character budget by turning the largest full diffs into summaries before it cuts any path to its
header, so every path keeps content a message can draw on.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, List, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "harness" / "lib"))

from conftest import git  # noqa: E402
from harness_lib import branch_capture  # noqa: E402
from harness_lib.branch_capture import path_diff, path_diffs  # noqa: E402
from harness_lib.commit_diff import DiffStat, fit_sections, render_section  # noqa: E402


def _changed_repo(make_project: Callable[..., Path]) -> Path:
    files = {"a.py": "a = 1\n", "b.py": "b = 1\n", "old.md": "\n".join(f"line {n}" for n in range(30)) + "\n"}
    root = make_project(config={}, files=files)
    (root / "a.py").write_text("a = 2\n", encoding="utf-8")
    (root / "b.py").write_text("b = 2\n", encoding="utf-8")
    git(root, "mv", "old.md", "new.md")
    (root / "new.txt").write_text("fresh\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("display", [
    (), ("diff.mnemonicPrefix", "true"), ("diff.noprefix", "true"), ("color.diff", "always"),
])
def test_batched_reads_equal_single_reads(
        make_project: Callable[..., Path], monkeypatch: pytest.MonkeyPatch, display: Tuple[str, ...],
) -> None:
    root = _changed_repo(make_project)
    if display:
        git(root, "config", *display)
    head = git(root, "rev-parse", "HEAD")
    pairs = [("a.py", None), ("b.py", None), ("new.md", "old.md"), ("new.txt", None)]
    untracked = frozenset({"new.txt"})
    diffs: List[Tuple[str, ...]] = []
    real = branch_capture.git_out

    def spy(repo: Path, *args: str) -> str:
        diffs.append(args) if "diff" in args else None
        return real(repo, *args)

    monkeypatch.setattr(branch_capture, "git_out", spy)
    batched = path_diffs(root, head, pairs, untracked)
    # One read for the tracked chunk; the untracked new.txt reads no git diff, and no path falls back.
    assert len(diffs) == 1, diffs
    for path, old in pairs:
        assert batched[path] == path_diff(root, head, path, old, path in untracked), path
    assert batched["new.md"].startswith("diff --git a/old.md b/new.md\n"), batched["new.md"]


def _hunks(path: str, count: int, width: int) -> str:
    body = [f"@@ -{n * 10},2 +{n * 10},2 @@ def f{n}():\n-" + "x" * width + "\n+" + "y" * width
            for n in range(count)]
    return f"diff --git a/{path} b/{path}\n" + "\n".join(body) + "\n"


def test_largest_full_diffs_become_summaries_before_any_path_is_cut() -> None:
    texts = {f"p{n}.py": _hunks(f"p{n}.py", 60, 150) for n in range(6)}
    stats = [DiffStat(path, 60, 60) for path in texts]
    sections = fit_sections(stats, {path: "full" for path in texts}, texts, budget=24_000)
    assert not [s for s in sections if "[omitted: block output budget spent]" in s], sections
    assert sum(len(s) + 1 for s in sections) <= 24_000
    assert any("[summary," in s for s in sections)


def test_the_larger_of_two_unranked_full_diffs_is_summarized_first() -> None:
    texts = {"small.py": _hunks("small.py", 20, 60), "big.py": _hunks("big.py", 40, 60)}
    stats = [DiffStat(path, 60, 60) for path in texts]
    full = [render_section(stat, "full", texts[stat.path]) for stat in stats]
    budget = sum(len(s) for s in full) + 1
    sections = fit_sections(stats, {p: "full" for p in texts}, texts, budget=budget)
    heads = {s.splitlines()[0] for s in sections}
    assert heads == {"=== small.py [full, +60 -60] ===", "=== big.py [summary, +60 -60] ==="}, heads


def test_a_higher_rank_is_summarized_before_a_larger_source_diff() -> None:
    texts = {"src.py": _hunks("src.py", 40, 60), "guide.md": _hunks("guide.md", 30, 60)}
    stats = [DiffStat(path, 60, 60) for path in texts]
    budget = len(render_section(stats[0], "full", texts["src.py"])) + 2_000
    sections = fit_sections(stats, {p: "full" for p in texts}, texts, budget=budget, rank={"guide.md": 2})
    assert "[full," in sections[0] and "[summary," in sections[1], [s.splitlines()[0] for s in sections]


def test_a_block_within_budget_is_left_as_planned() -> None:
    texts = {"a.py": _hunks("a.py", 2, 10), "b.py": _hunks("b.py", 2, 10)}
    stats = [DiffStat(path, 2, 2) for path in texts]
    sections = fit_sections(stats, {"a.py": "full", "b.py": "full"}, texts)
    assert all("[full," in s for s in sections)
