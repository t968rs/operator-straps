"""Behavioral tests for harness_lib.pr_viz: the qualifying-block rule behind ``--min-viz``.

A qualifying block is fenced, closed, longer than ``MIN_BLOCK_CHARS`` characters inside the fence, and holds
at least one arrow.
"""
from __future__ import annotations

from typing import List

import pytest

from harness_lib.pr_summary import PrDraft, PrSection
from harness_lib.pr_viz import (
    DEFAULT_MIN_VIZ,
    MIN_BLOCK_CHARS,
    count_qualifying,
    is_qualifying,
    min_viz_problems,
)


def _block(arrow: str = "──►", size: int = MIN_BLOCK_CHARS + 1) -> str:
    """A fenced block of ``size`` characters inside the fence, carrying ``arrow``."""
    body = (f"step one {arrow} step two\n" * size)[: size - 1] + "x"
    return f"```\n{body}\n```"


class TestIsQualifying:
    @pytest.mark.parametrize("arrow", ["──►", "->", "=>", "→", "▼", "▲", "◄──", "⟶", "➜", "▶"])
    def test_arrow_glyphs(self, arrow: str) -> None:
        assert is_qualifying(_lines(_block(arrow)))

    def test_no_arrow(self) -> None:
        body = ("plain text line\n" * 20).strip()
        assert len(body) > MIN_BLOCK_CHARS
        assert not is_qualifying(body.splitlines())

    def test_length_is_strictly_over_the_limit(self) -> None:
        at_limit = "a" * (MIN_BLOCK_CHARS - 2) + "->"
        assert len(at_limit) == MIN_BLOCK_CHARS
        assert not is_qualifying([at_limit])
        assert is_qualifying([at_limit + "x"])

    def test_length_counts_newlines_between_lines(self) -> None:
        lines = ["a" * 98 + "->", "b" * 100]
        assert len("\n".join(lines)) == MIN_BLOCK_CHARS + 1
        assert is_qualifying(lines)


def _lines(block: str) -> List[str]:
    return block.splitlines()[1:-1]


class TestCountQualifying:
    def test_counts_each_closed_block(self) -> None:
        assert count_qualifying("\n\n".join([_block(), "prose", _block("->")])) == 2

    def test_skips_short_and_arrowless_blocks(self) -> None:
        short = "```\na -> b\n```"
        arrowless = "```\n" + "z" * 300 + "\n```"
        assert count_qualifying("\n\n".join([short, arrowless, _block()])) == 1

    def test_unclosed_trailing_fence_does_not_count(self) -> None:
        text = _block() + "\n\n```\n" + "a -> b " * 60
        assert count_qualifying(text) == 1

    def test_indented_fence_counts(self) -> None:
        text = "\n".join("  " + line for line in _block().splitlines())
        assert count_qualifying(text) == 1

    def test_no_fences(self) -> None:
        assert count_qualifying("just prose -> with an arrow") == 0


class TestMinVizProblems:
    def _draft(self, *blocks: str, summary: str = "Summary.") -> PrDraft:
        sections = tuple(PrSection(f"Behavior: {n}", block) for n, block in enumerate(blocks))
        return PrDraft(summary=summary, sections=sections)

    def test_default_is_three(self) -> None:
        assert DEFAULT_MIN_VIZ == 3

    def test_enough_blocks_pass(self) -> None:
        assert min_viz_problems(self._draft(_block(), _block(), _block()), 3) == []

    def test_shortfall_reports_found_count(self) -> None:
        assert min_viz_problems(self._draft(_block(), _block()), 3) == [
            "--min-viz needs 3 diagram blocks (fenced, over 200 characters, with an arrow); found 2",
        ]

    def test_summary_fences_count(self) -> None:
        draft = self._draft(_block(), summary="Intro.\n\n" + _block())
        assert min_viz_problems(draft, 2) == []

    def test_zero_minimum_disables(self) -> None:
        assert min_viz_problems(self._draft(), 0) == []
