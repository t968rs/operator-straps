"""Behavioral tests for harness_lib.pr_compare: the comparison flow rules of a pr-sum ``Behavior:`` fence.

Most tests build one fence as a list of lines and read the problem lines ``comparison_problems`` returns;
``TestIsComparison`` checks header detection alone. Columns in the expected lines are 1-based.
"""
from __future__ import annotations

from typing import List

import pytest

from harness_lib.pr_compare import comparison_problems, is_comparison

_HEAD = "BEFORE              AFTER                         [CHANGE]"
_W = "s: fence 1"


def _row(before: str, marker: str, after: str, tag: str = "") -> str:
    """One comparison row: BEFORE text to column 17, the marker, AFTER text from column 21, the tag at the
    ``[CHANGE]`` column of ``_HEAD``."""
    line = before.ljust(17) + marker.ljust(3) + after
    return (line.ljust(_HEAD.index("[CHANGE]")) + tag) if tag else line


def _problems(*lines: str) -> List[str]:
    """Problems of one fence headed by ``_HEAD``."""
    return comparison_problems("s", 1, [_HEAD, *lines])


class TestIsComparison:
    @pytest.mark.parametrize("line, expected", [
        (_HEAD, True), ("BEFORE   AFTER", False), ("AFTER  [CHANGE]", False), ("  " + _HEAD, True),
    ])
    def test_header_needs_all_three_names(self, line: str, expected: bool) -> None:
        assert is_comparison(line) is expected


class TestComparisonRules:
    def test_marked_steps_pass(self) -> None:
        assert _problems(
            "run the tool", "     │", "     ▼",
            _row("read table", "<>", "read check boxes", "[changed]"),
            _row("     │", ">>", "boundary given?", "[new]"),
            _row("drop rows", "<<", "", "[removed]"),
        ) == []

    def test_tag_on_a_continuation_line_passes(self) -> None:
        first = _row("run each", "<>", "run checked [[in")
        assert _problems(first, _row("method", "", "order]]", "[changed]")) == []

    def test_header_order(self) -> None:
        problems = comparison_problems("s", 1, ["BEFORE [CHANGE] AFTER", _row("a", "<>", "b")])
        assert f"{_W}: the first line names the columns in the order BEFORE, AFTER, [CHANGE]" in problems

    def test_no_marker(self) -> None:
        assert _problems("same step") == [
            f"{_W}: a comparison flow marks each changed step with '<>', '>>' or '<<'",
        ]

    def test_marked_step_without_tag(self) -> None:
        assert _problems(_row("a", "<>", "b"), "     │") == [
            f"{_W}, fence line 2: the step marked '<>' needs [changed]",
        ]

    def test_wrong_tag_for_marker(self) -> None:
        assert _problems(_row("     │", ">>", "b", "[changed]")) == [
            f"{_W}, fence line 2: marker '>>' takes [new], not [changed]",
        ]

    def test_tag_without_marker(self) -> None:
        assert _problems(_row("a", "<>", "b", "[changed]"), "     │", _row("c", "", "d", "[new]")) == [
            f"{_W}, fence line 4: [new] has no marker on its step; mark the step '>>'",
        ]

    def test_two_tags_on_one_step(self) -> None:
        assert _problems(_row("a", "<>", "b", "[changed]"), _row("a2", "", "b2", "[changed]")) == [
            f"{_W}, fence line 2: the step marked '<>' holds 2 tags; one per step",
        ]

    def test_two_markers_on_one_line(self) -> None:
        problems = _problems(_row("a", "<>", "b >> c", "[changed]"))
        assert f"{_W}, fence line 2: 2 markers on one line; one step per marker" in problems

    def test_text_after_a_tag(self) -> None:
        problems = _problems(_row("a", "<>", "b", "[changed]") + " more")
        assert f"{_W}, fence line 2: [changed] is not the last text on its line" in problems

    def test_tag_off_the_change_column(self) -> None:
        assert _problems(_row("a", "<>", "b") + "  [changed]") == [
            f"{_W}, fence line 2: [changed] starts at column 24; the [CHANGE] column is 51",
        ]

    def test_markers_in_two_columns(self) -> None:
        shifted = _row("a", "<>", "b", "[changed]").replace("  <> ", " <>  ")
        assert _problems(shifted, "     │", _row("     │", ">>", "c", "[new]")) == [
            f"{_W}: markers sit in columns 17, 18; use one gutter column",
        ]

    @pytest.mark.parametrize("after, problem", [
        ("b ]] c", "unbalanced ]] emphasis"), ("[[b [[c", "unbalanced [[ emphasis"),
        ("[[b", "[[ emphasis never closes with ]]"),
    ])
    def test_unbalanced_emphasis(self, after: str, problem: str) -> None:
        assert _problems(_row("a", "<>", after, "[changed]")) == [f"{_W}, fence line 2: {problem}"]

    def test_tabs_expand_before_columns(self) -> None:
        tabbed = "a\t\t <>  b"
        assert tabbed.expandtabs().index("<>") == 17
        assert _problems(tabbed + " " * (_HEAD.index("[CHANGE]") - 22) + "[changed]") == []
