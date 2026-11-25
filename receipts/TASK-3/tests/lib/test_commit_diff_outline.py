"""Tests for the hunk outline ``commit_diff.summarize_diff`` gives an over-budget text diff.

A truncated head shows only the first hunks of a large edit, so a drafter reads the file again to see the
rest. The outline names every hunk (its ``@@`` header and change counts) with a few changed lines each, under
a fixed line budget; past that budget the remaining hunks are counted, not named, so the summary stays bounded
as the hunk count grows.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "harness" / "lib"))

from harness_lib import commit_diff  # noqa: E402


def _hunk(start: int, name: str, changed: int) -> str:
    """One hunk at ``start`` inside ``def name`` replacing ``changed`` lines."""
    head = f"@@ -{start},{changed} +{start},{changed} @@ def {name}():"
    removed = [f"-    old_{name}_{n} = {n}" for n in range(changed)]
    added = [f"+    new_{name}_{n} = {n}" for n in range(changed)]
    return "\n".join([head, *removed, *added])


def _diff(hunks: int, changed: int) -> str:
    header = "diff --git a/src/big.py b/src/big.py\nindex 1..2 100644\n--- a/src/big.py\n+++ b/src/big.py"
    body = [_hunk(10 + 40 * n, f"fn{n}", changed) for n in range(hunks)]
    return "\n".join([header, *body]) + "\n"


def test_every_hunk_header_survives_the_summary() -> None:
    text = commit_diff.summarize_diff("src/big.py", _diff(hunks=30, changed=6))
    for n in range(30):
        assert f"def fn{n}():" in text, n


def test_each_hunk_carries_its_change_counts() -> None:
    text = commit_diff.summarize_diff("src/big.py", _diff(hunks=3, changed=50))
    assert text.count("[+50 -50]") == 3, text


def test_each_hunk_shows_its_first_changed_lines() -> None:
    text = commit_diff.summarize_diff("src/big.py", _diff(hunks=3, changed=50))
    for n in range(3):
        assert f"old_fn{n}_0 = 0" in text and f"new_fn{n}_0 = 0" in text, n


def test_the_outline_stays_within_the_line_budget() -> None:
    small = commit_diff.summarize_diff("src/big.py", _diff(hunks=20, changed=40)).splitlines()
    large = commit_diff.summarize_diff("src/big.py", _diff(hunks=20, changed=400)).splitlines()
    assert len(large) == len(small)
    assert len(large) <= commit_diff.OUTLINE_LINES


def test_past_the_budget_the_rest_are_counted() -> None:
    text = commit_diff.summarize_diff("src/big.py", _diff(hunks=200, changed=6))
    lines = text.splitlines()
    listed = commit_diff.OUTLINE_LINES - 2
    assert len(lines) == commit_diff.OUTLINE_LINES, len(lines)
    assert lines[-1] == f"... {200 - listed} more hunks omitted", lines[-1]
    assert f"def fn{listed - 1}():" in lines[-2], lines[-2]
    assert f"def fn{listed}():" not in text


def test_a_single_hunk_diff_keeps_the_head() -> None:
    text = commit_diff.summarize_diff("src/big.py", _diff(hunks=1, changed=60))
    assert "more diff lines omitted" in text


def test_a_new_file_lists_the_definitions_past_its_head() -> None:
    body = [f"+def helper_{n}():\n+    return {n}\n+" for n in range(40)]
    text = commit_diff.summarize_diff("src/new.py", "+\"\"\"New module.\"\"\"\n" + "\n".join(body))
    assert "definitions past the head:" in text
    assert "+ def helper_39():" in text
