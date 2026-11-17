"""Behavioral tests for ``harness_lib.commit_diff``.

Covers numstat parsing, per-path and per-block read budgets, and diff summaries.
"""
from __future__ import annotations

import re
from typing import List, Sequence

from harness_lib.commit_diff import (
    ADDED_PATH_BUDGET,
    BLOCK_BUDGET,
    BLOCK_CHAR_BUDGET,
    LINE_WIDTH,
    SECTION_CHAR_BUDGET,
    JSON_PATH_BUDGET,
    JSON_TOP_KEYS,
    PATH_BUDGET,
    DiffStat,
    cap_sections,
    clip_text,
    parse_numstat_z,
    path_budget,
    plan_reads,
    read_budget,
    summarize_diff,
)


def _stat(path: str, changed: int) -> DiffStat:
    """Build a modification stat (one deleted line) with ``changed`` total changed lines."""
    return DiffStat(path=path, added=changed - 1, deleted=1)


class TestParseNumstatZ:
    def test_plain_and_rename_and_binary(self) -> None:
        text = "3\t1\ta.py\0" "0\t0\t\0old.py\0new.py\0" "-\t-\timg.png\0"
        assert parse_numstat_z(text) == [
            DiffStat("a.py", 3, 1),
            DiffStat("new.py", 0, 0),
            DiffStat("img.png", 0, 0),
        ]

    def test_empty(self) -> None:
        assert parse_numstat_z("") == []

    def test_changed_sums_both_sides(self) -> None:
        assert DiffStat("a.py", 3, 4).changed == 7


class TestPathBudget:
    def test_json_is_tighter_than_source(self) -> None:
        assert path_budget("data/x.json") == JSON_PATH_BUDGET < path_budget("src/x.py") == PATH_BUDGET

    def test_suffix_case_insensitive(self) -> None:
        assert path_budget("data/X.JSON") == JSON_PATH_BUDGET


class TestReadBudget:
    def test_pure_addition_is_tighter_than_modification(self) -> None:
        pure_addition = read_budget(DiffStat("n.py", 10, 0))
        modification = read_budget(DiffStat("n.py", 10, 1))
        assert pure_addition == ADDED_PATH_BUDGET < modification == PATH_BUDGET

    def test_json_budget_wins_when_tighter(self) -> None:
        assert read_budget(DiffStat("n.json", 10, 0)) == JSON_PATH_BUDGET

    def test_empty_change_is_not_an_addition(self) -> None:
        assert read_budget(DiffStat("n.py", 0, 0)) == PATH_BUDGET


class TestPlanReads:
    def test_new_file_over_added_budget_is_summary(self) -> None:
        assert plan_reads([DiffStat("new.py", ADDED_PATH_BUDGET + 1, 0)]) == {"new.py": "summary"}

    def test_modified_file_at_same_size_is_full(self) -> None:
        assert plan_reads([DiffStat("old.py", ADDED_PATH_BUDGET + 1, 1)]) == {"old.py": "full"}

    def test_small_paths_are_full(self) -> None:
        assert plan_reads([_stat("a.py", 10), _stat("b.md", 20)]) == {"a.py": "full", "b.md": "full"}

    def test_over_path_budget_is_summary(self) -> None:
        assert plan_reads([_stat("big.py", PATH_BUDGET + 1)]) == {"big.py": "summary"}

    def test_json_uses_json_budget(self) -> None:
        modes = plan_reads([_stat("a.json", JSON_PATH_BUDGET + 1), _stat("a.py", JSON_PATH_BUDGET + 1)])
        assert modes == {"a.json": "summary", "a.py": "full"}

    def test_block_budget_demotes_later_paths(self) -> None:
        each = PATH_BUDGET
        count = BLOCK_BUDGET // each + 1
        modes = plan_reads([_stat(f"f{n}.py", each) for n in range(count)])
        assert list(modes.values()).count("full") == BLOCK_BUDGET // each
        assert modes[f"f{count - 1}.py"] == "summary"

    def test_summary_paths_do_not_consume_block_budget(self) -> None:
        modes = plan_reads([_stat("huge.json", 10_000), _stat("a.py", PATH_BUDGET)])
        assert modes == {"huge.json": "summary", "a.py": "full"}


def _json_diff(entries: int) -> str:
    """Unified diff text for a JSON file where each entry changes ``summary`` and adds ``added_in_pr``."""
    lines: List[str] = ["diff --git a/r.json b/r.json", "--- a/r.json", "+++ b/r.json", "@@ -1,1 +1,1 @@"]
    for n in range(entries):
        lines += [
            f'-      "summary": "old {n}",',
            f'+      "summary": "new {n}",',
            f'+      "added_in_pr": {n},',
        ]
    return "\n".join(lines) + "\n"


def _keyed_json_diff(sizes: Sequence[int]) -> str:
    """Unified diff text adding ``sizes[i]`` lines under top-level key ``key_{i}``."""
    lines: List[str] = ["--- a/r.json", "+++ b/r.json", "@@ -1 +1 @@"]
    for idx, size in enumerate(sizes):
        lines += [f'+  "key_{idx}": {n},' for n in range(size)]
    return "\n".join(lines) + "\n"


_TALLY_LINE = re.compile(r"^  \S.*: \+\d+ -\d+$")


class TestClipText:
    def test_short_text_is_unchanged(self) -> None:
        assert clip_text("a\nb\n") == "a\nb"

    def test_long_line_is_cut_with_char_count(self) -> None:
        out = clip_text("x" * 5000)
        assert out.startswith("x" * LINE_WIDTH)
        assert out.endswith(f"[+{5000 - LINE_WIDTH} chars]")
        assert len(out) < LINE_WIDTH + 40

    def test_megabyte_line_stays_bounded(self) -> None:
        assert len(clip_text("y" * 2_000_000)) < LINE_WIDTH + 40

    def test_many_lines_stop_at_char_budget(self) -> None:
        out = clip_text("\n".join("z" * 100 for _ in range(1000)))
        assert len(out) < SECTION_CHAR_BUDGET + 100
        assert out.splitlines()[-1].startswith("... ") and "omitted" in out.splitlines()[-1]

    def test_summaries_are_clipped_too(self) -> None:
        text = "@@ -1 +1 @@\n+" + "w" * 5000 + "\n"
        assert max(len(line) for line in summarize_diff("m.py", text).splitlines()) < LINE_WIDTH + 40


class TestCapSections:
    def test_within_budget_is_unchanged(self) -> None:
        sections = ["=== a ===\nbody a", "=== b ===\nbody b"]
        assert cap_sections(sections) == sections

    def test_sections_past_budget_keep_only_their_header(self) -> None:
        big = "=== a ===\n" + "q" * BLOCK_CHAR_BUDGET
        out = cap_sections([big, "=== b ===\nbody b"])
        assert out[0] == big
        assert out[1] == "=== b ===\n[omitted: block output budget spent]"


class TestSummarizeDiff:
    def test_json_tallies_keys(self) -> None:
        out = summarize_diff("r.json", _json_diff(50))
        assert "summary: +50 -50" in out
        assert "added_in_pr: +50 -0" in out

    def test_json_non_key_lines_are_not_tallied(self) -> None:
        text = (
            "--- a/r.json\n+++ b/r.json\n@@ -1 +1 @@\n-  {\n+  {\n"
            '+      "k": 1,\n+      "j": 2,\n+      "m": 3,\n'
        )
        out = summarize_diff("r.json", text)
        assert "k: +1 -0" in out
        assert "{" not in out

    def test_json_summary_is_bounded(self) -> None:
        sizes = range(1, JSON_TOP_KEYS + 4)
        out = summarize_diff("r.json", _keyed_json_diff(sizes))
        tally_lines = [line for line in out.splitlines() if _TALLY_LINE.match(line)]
        assert len(tally_lines) == JSON_TOP_KEYS
        assert tally_lines[0] == f"  key_{len(sizes) - 1}: +{max(sizes)} -0"

    def test_json_header_counts_shown_keys(self) -> None:
        out = summarize_diff("r.json", _keyed_json_diff([2, 1]))
        assert out.splitlines()[0] == "r.json: JSON diff summary, 2 keys changed (top 2 shown)"

    def test_json_array_only_change_falls_back_to_diff_head(self) -> None:
        text = "--- a/r.json\n+++ b/r.json\n@@ -1 +1 @@\n-    1,\n+    2,\n+    3,\n"
        out = summarize_diff("r.json", text)
        assert "0 keys changed (top 0 shown)" in out
        assert "+    2," in out
        assert "+    3," in out

    def test_json_mostly_unkeyed_change_falls_back_to_diff_head(self) -> None:
        text = '@@ -1 +1 @@\n+  "k": [\n+    1,\n+    2,\n+    3,\n'
        out = summarize_diff("r.json", text)
        assert "k: +1 -0" in out
        assert "+    3," in out

    def test_json_samples_are_trimmed(self) -> None:
        long_line = "+      \"summary\": \"" + "x" * 500 + "\",\n"
        out = summarize_diff("r.json", "@@ -1 +1 @@\n" + long_line)
        assert max(len(line) for line in out.splitlines()) <= 120

    def test_text_diff_is_truncated_with_marker(self) -> None:
        text = "@@ -1 +1 @@\n" + "".join(f"+line {n}\n" for n in range(1000))
        out = summarize_diff("m.py", text)
        assert out.splitlines()[0] == "@@ -1 +1 @@"
        assert "more diff lines omitted" in out
        assert len(out.splitlines()) <= 60

    def test_short_text_diff_passes_through(self) -> None:
        text = "@@ -1 +1 @@\n-a\n+b\n"
        assert summarize_diff("m.py", text) == text.rstrip("\n")
