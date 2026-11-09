"""Behavioral tests for harness_lib.pr_align: the vertical alignment pass ``build`` runs at levels 2 and 3.

Tables, hanging connectors, comparison markers and change tags are aligned by moving spaces only; what the
pass cannot place stays as written. The pr-sum SKILL.md comparison example must be a fixed point of the pass.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, List

import pytest

from harness_lib.config import activate, load_config
from harness_lib.pr_align import align_body, align_draft, align_fence, align_table, snap_connectors
from harness_lib.pr_summary import PrDraft, PrFacts, PrFile, PrSection, draft_problems


@pytest.fixture(autouse=True)
def _project(make_project: Callable[..., Path]) -> Path:
    """A project with no ``harness.json`` overrides, activated for the test."""
    root = make_project()
    activate(load_config(root))
    return root


def _skill_example(plugin_root: Path) -> List[str]:
    """Lines of the comparison flow example in the pr-sum SKILL.md."""
    text = (plugin_root / "skills" / "pr-sum" / "SKILL.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```\n(BEFORE .*?)\n```", text, re.S)
    assert len(blocks) == 1
    return blocks[0].splitlines()


def _text(lines: List[str]) -> List[str]:
    """Each line's text with its spaces removed."""
    return ["".join(line.split()) for line in lines]


class TestAlignTable:
    def test_pipes_line_up(self) -> None:
        rows = ["| Symbol | File | Status |", "|---|---|---|", "| `run_diff` | pr_sum.py | CHANGED |"]
        assert align_table(rows) == [
            "| Symbol     | File      | Status  |",
            "| ---------- | --------- | ------- |",
            "| `run_diff` | pr_sum.py | CHANGED |",
        ]

    def test_colons_keep_their_padding(self) -> None:
        rows = ["| a | n | c |", "|:--|--:|:-:|", "| long | 7 | x |"]
        assert align_table(rows) == [
            "| a    |   n |  c  |",
            "| :--- | --: | :-: |",
            "| long |   7 |  x  |",
        ]

    def test_escaped_pipe_stays_in_its_cell(self) -> None:
        rows = ["| a | b |", "|---|---|", "| x \\| y | z |"]
        assert align_table(rows)[2] == "| x \\| y | z   |"

    @pytest.mark.parametrize("rows", [
        ["| a | b |", "|---|", "| c | d |"],
        ["| a | b |", "| c | d |"],
        ["| a | b |"],
    ])
    def test_ragged_or_ruleless_tables_stay(self, rows: List[str]) -> None:
        assert align_table(rows) == rows


class TestSnapConnectors:
    def test_hanging_run_slides_under_the_text(self) -> None:
        lines = ["read matrix", "             │", "             ▼", "done"]
        assert snap_connectors(lines) == ["read matrix", "          │", "          ▼", "done"]

    def test_label_moves_with_its_connector(self) -> None:
        lines = ["matrix exists? ──no──► write", "  │yes", "  ▼", "read"]
        assert snap_connectors(lines)[1:3] == ["  │yes", "  ▼"]
        lines = ["    matrix exists? ──no──► write", "  │yes", "  ▼", "read"]
        assert snap_connectors(lines)[1:3] == ["    │yes", "    ▼"]

    def test_out_of_reach_stays(self) -> None:
        lines = ["read", "          │", "          ▼", "done"]
        assert snap_connectors(lines) == lines

    def test_blocked_target_stays(self) -> None:
        lines = ["ab", "z │", "done"]
        assert snap_connectors(lines) == lines


class TestComparisonFence:
    _FENCE = [
        "BEFORE           AFTER        [CHANGE]",
        "read table  <>   read boxes  [changed]",
        "     │",
        "     │       >>  boundary given?      [new]",
    ]

    def test_markers_and_tags_line_up(self) -> None:
        assert align_fence(self._FENCE) == [
            "BEFORE           AFTER            [CHANGE]",
            "read table  <>   read boxes       [changed]",
            "     │",
            "     │      >>   boundary given?  [new]",
        ]

    def test_text_never_changes(self) -> None:
        assert _text(align_fence(self._FENCE)) == _text(self._FENCE)

    def test_pass_is_idempotent(self) -> None:
        once = align_fence(self._FENCE)
        assert align_fence(once) == once

    def test_unmoved_fence_keeps_its_tabs(self) -> None:
        block = ["\tread", "         │", "         ▼", "\tdone"]
        assert align_fence(block) == block

    def test_skill_example_is_a_fixed_point(self, plugin_root: Path) -> None:
        lines = _skill_example(plugin_root)
        assert align_fence(lines) == lines


def _facts() -> PrFacts:
    """One modified source file."""
    files = (PrFile("M", "src/a.py", None, 1, 1),)
    return PrFacts(7, "t", "h", "main", "h" * 40, "m" * 40, "2026-11-07", (), files)


class TestAlignDraft:
    _TABLE = "| Symbol | File | Status |\n|---|---|---|\n| `a` | A | NEW |"

    def test_level_one_is_left_alone(self) -> None:
        draft = PrDraft("t", "s", {}, (PrSection("Changed Symbols", self._TABLE),))
        assert align_draft(draft, 1) == draft

    def test_shape_fences_stay_and_tables_align(self) -> None:
        body = "```\nsource ──► stage\n             ▼\n```\n" + self._TABLE
        aligned = align_draft(PrDraft("t", "s", {}, (PrSection("Data Flow", body),)), 3).sections[0].body
        assert aligned.startswith("```\nsource ──► stage\n             ▼\n```\n| Symbol | File | Status |")

    def test_aligned_skill_example_builds(self, plugin_root: Path) -> None:
        body = "\n".join(["```", *_skill_example(plugin_root), "```"])
        sections = (PrSection("Behavior: append", body), PrSection("Changed Symbols", self._TABLE))
        draft = align_draft(PrDraft("T(a): `a` b", "s", {"src/a.py": "x"}, sections), 2)
        assert draft_problems(_facts(), draft) == []
        assert draft.sections[0].body == body

    def test_unclosed_fence_stays(self) -> None:
        body = "```\nread\n             │"
        assert align_body(body, True) == body
