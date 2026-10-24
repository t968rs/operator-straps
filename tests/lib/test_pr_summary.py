"""Behavioral tests for harness_lib.pr_summary: facts, draft checks, payload round trip, markdown layout.

Every test runs against a throwaway project with the plugin-default harness configuration activated, so
artifact classification (``PrFile.artifact`` through ``branch_commits.path_bucket``) never depends on the
checkout the suite runs from.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

import pytest

from harness_lib.config import activate, load_config
from harness_lib.pr_summary import (
    DEFAULT_LEVEL,
    PrDraft,
    PrFacts,
    PrFile,
    PrSection,
    artifact_note,
    draft_from_payload,
    draft_problems,
    facts_from_payload,
    new_draft,
    render_summary,
    skeleton,
    summary_filename,
)


@pytest.fixture(autouse=True)
def _project(make_project: Callable[..., Path]) -> Path:
    """A project with no ``harness.json`` overrides, activated for the test."""
    root = make_project()
    activate(load_config(root))
    return root


def _facts(**overrides: object) -> PrFacts:
    """Three-file PR: a modified source, a pure move, and a large artifact."""
    files = (
        PrFile("M", "src/pkg/a.py", None, 3, 1),
        PrFile("R", "docs/new/b.md", "docs/old/b.md", 0, 0),
        PrFile("A", "docs/PR_REVIEWS/0007_Demo.json", None, 40, 0),
    )
    values: Dict[str, object] = {
        "number": 7, "pr_title": "raw title", "head": "0007-demo", "base": "dev", "head_sha": "h" * 40,
        "merge_base": "m" * 40, "date": "2026-10-10", "commits": ("abc1234 Feature(a): add a",),
        "files": files,
    }
    return PrFacts(**{**values, **overrides})


_FLOW = PrSection("New Behavior: append", "```\nrows ready\n```")
_SYMBOLS = PrSection("Changed Symbols", "| Symbol | File | Status |\n|---|---|---|\n| `a` | A | NEW |")


def _draft(**overrides: object) -> PrDraft:
    """Complete plain draft for ``_facts()``."""
    values: Dict[str, object] = {
        "title": "Feature(a): `a` parameter", "summary": "Adds `a`.",
        "descriptions": {"src/pkg/a.py": "adds `a`"},
    }
    return PrDraft(**{**values, **overrides})


class TestPrFile:
    def test_pure_rename_is_relocated(self) -> None:
        assert PrFile("R", "n.py", "o.py", 0, 0).relocated
        assert not PrFile("R", "n.py", "o.py", 1, 0).relocated

    def test_binary_rename_is_not_relocated(self) -> None:
        assert not PrFile("R", "n.png", "o.png", 0, 0, binary=True).relocated

    def test_artifact_by_path(self) -> None:
        assert PrFile("M", "docs/PR_REVIEWS/1_x.json", None, 1, 0).artifact
        assert not PrFile("M", "src/pkg/a.py", None, 1, 0).artifact


class TestPrFacts:
    def test_totals_and_partitions(self) -> None:
        facts = _facts()
        assert (facts.additions, facts.deletions) == (43, 1)
        assert [f.path for f in facts.listed] == [
            "src/pkg/a.py", "docs/PR_REVIEWS/0007_Demo.json",
        ]
        assert [f.path for f in facts.relocated] == ["docs/new/b.md"]
        assert facts.described == ("src/pkg/a.py",)


class TestPayload:
    def test_round_trip(self) -> None:
        facts, draft = _facts(), _draft(sections=(PrSection("Changed Symbols", "```\nx\n```"),))
        payload = skeleton(facts, draft)
        assert facts_from_payload(payload["facts"]) == facts
        assert draft_from_payload(payload["draft"]) == draft

    def test_line_lists_join(self) -> None:
        raw = {
            "summary": ["One.", "", "Two."],
            "sections": [{"heading": "Legend", "body": ["```", "A=b", "```"]}],
        }
        draft = draft_from_payload(raw)
        assert draft.summary == "One.\n\nTwo."
        assert draft.sections == (PrSection("Legend", "```\nA=b\n```"),)

    def test_new_draft_lists_described_paths(self) -> None:
        assert new_draft(_facts()).descriptions == {"src/pkg/a.py": ""}

    def test_payload_without_binary_key(self) -> None:
        payload = skeleton(_facts(), _draft())["facts"]
        for entry in payload["files"]:
            entry.pop("binary")
        assert facts_from_payload(payload) == _facts()

    def test_payload_without_source_fields_reads_as_remote_committed(self) -> None:
        raw = skeleton(_facts(), _draft())["facts"]
        for key in ("head_source", "working_tree", "local_branch"):
            raw.pop(key)
        for entry in raw["files"]:
            entry.pop("untracked")
        assert facts_from_payload(raw) == _facts()

    def test_description_values_coerced(self) -> None:
        draft = draft_from_payload({"descriptions": {"a.py": None, "b.py": ["x", "y"], "c.py": "z"}})
        assert draft.descriptions == {"a.py": "", "b.py": "x\ny", "c.py": "z"}


class TestSummaryFilename:
    def test_underscored_title(self) -> None:
        assert summary_filename(7, "Feature(a): `a` parameter") == "0007_Feature_a_a_parameter.md"


class TestArtifactNote:
    def test_emitted_when_artifacts_dominate(self) -> None:
        assert artifact_note(_facts()) == (
            "***Note:*** 1 machine-generated artifact file(s) account for +40/-0 of the +43/-1 headline; "
            "the source delta is +3/-1."
        )

    def test_absent_when_source_dominates(self) -> None:
        assert artifact_note(_facts(files=(PrFile("M", "src/pkg/a.py", None, 3, 1),))) is None

    def test_exact_half_boundary(self) -> None:
        source = PrFile("M", "src/pkg/a.py", None, 1, 1)
        half = PrFile("A", "docs/PR_REVIEWS/1_x.json", None, 2, 0)
        over = PrFile("A", "docs/PR_REVIEWS/1_x.json", None, 3, 0)
        assert artifact_note(_facts(files=(source, half))) is None
        assert artifact_note(_facts(files=(source, over))) == (
            "***Note:*** 1 machine-generated artifact file(s) account for +3/-0 of the +4/-1 headline; "
            "the source delta is +1/-1."
        )


class TestDraftProblems:
    def test_complete_draft_passes(self) -> None:
        assert draft_problems(_facts(), _draft(sections=(_FLOW, _SYMBOLS))) == []

    def test_empty_fields_and_descriptions(self) -> None:
        problems = draft_problems(_facts(), PrDraft(descriptions={"nope.py": "x"}), level=1)
        assert problems == [
            "draft title is empty", "draft summary is empty", "no description for `src/pkg/a.py`",
            "description for `nope.py`, which is not a changed path",
        ]

    def test_multiline_title(self) -> None:
        draft = draft_from_payload({**skeleton(_facts(), _draft())["draft"], "title": ["Feature(a):", "two"]})
        assert draft_problems(_facts(), draft, level=1) == ["draft title spans more than one line"]

    def test_empty_heading_reported_once(self) -> None:
        draft = _draft(sections=(_FLOW, PrSection("  ", "x"), _SYMBOLS))
        assert draft_problems(_facts(), draft) == ["a section has no heading"]

    def test_unclosed_fence_reads_as_fenced(self) -> None:
        body = "```\nBEFORE\nwrite rows\n```\n```\nAFTER\nkeep file  [changed]\n" + "w" * 121
        draft = _draft(sections=(PrSection("Behavior: append", body), _SYMBOLS))
        assert draft_problems(_facts(), draft) == [
            "section 'Behavior: append': monospace line of 121 chars (limit 120)",
        ]

    def test_default_level_needs_sections(self) -> None:
        assert draft_problems(_facts(), _draft()) == [
            "a visual summary needs its sections (behavior flows or a shape diagram, Changed Symbols)",
        ]

    def test_long_monospace_line(self) -> None:
        symbols = PrSection("Changed Symbols", "```\n" + "x" * 121 + "\n```\n" + "y" * 200)
        assert draft_problems(_facts(), _draft(sections=(_FLOW, symbols))) == [
            "section 'Changed Symbols': monospace line of 121 chars (limit 120)",
        ]

    def test_long_table_cell(self) -> None:
        rows = ["| Symbol | File | Note |", "|---|---|---|", "| `writeRows` | T | " + "z" * 41 + " |"]
        fenced = ["```", "| " + "q" * 60 + " |", "```"]
        draft = _draft(sections=(_FLOW, PrSection("Changed Symbols", "\n".join(rows + fenced))))
        assert draft_problems(_facts(), draft) == [
            "section 'Changed Symbols': table cell of 41 chars (limit 40); "
            "move the text above or below the table",
        ]

    def test_escaped_pipe_stays_in_cell(self) -> None:
        body = "| Symbol | Note |\n|---|---|\n| `a \\| b` | ok |"
        draft = _draft(sections=(_FLOW, PrSection("Changed Symbols", body)))
        assert draft_problems(_facts(), draft) == []

    def test_behavior_flow_needs_labels(self) -> None:
        body = "```\nrows ready\n```\n```\nAFTER\nrows ready\n```"
        draft = _draft(sections=(PrSection("Behavior: append", body), _SYMBOLS))
        assert draft_problems(_facts(), draft) == [
            "section 'Behavior: append': needs a fence whose first line is BEFORE and one whose first line "
            "is AFTER, or one side-by-side fence whose first line holds both",
        ]

    def test_behavior_flow_tags_only_after(self) -> None:
        body = "```\nBEFORE\nwrite rows  [changed]\n```\n```\nAFTER\nkeep file  [changed]\n```"
        draft = _draft(sections=(PrSection("Behavior: append", body), _SYMBOLS))
        assert draft_problems(_facts(), draft) == [
            "section 'Behavior: append': [changed] / [new] tags belong in the AFTER flow only",
        ]

    def test_side_by_side_flow_passes(self) -> None:
        body = "```\nBEFORE          AFTER\nwrite rows      keep file  [changed]\n```"
        draft = _draft(sections=(PrSection("Behavior: x", body), _SYMBOLS))
        assert draft_problems(_facts(), draft) == []

    def test_complete_visual_layout(self) -> None:
        draft = _draft(sections=(_FLOW, PrSection("Rule Illustration", "x"), _SYMBOLS))
        assert draft_problems(_facts(), draft) == []

    def test_layout_unknown_and_missing(self) -> None:
        draft = _draft(sections=(PrSection("Legend", "x"),))
        assert draft_problems(_facts(), draft) == [
            "section 'Legend': unknown heading; use 'Behavior: <trigger>', 'New Behavior: <trigger>', "
            "a shape diagram name or 'Changed Symbols'",
            "a visual summary needs a behavior flow or a shape diagram",
            "a visual summary needs exactly one 'Changed Symbols' section (found 0)",
        ]

    def test_layout_counts_and_order(self) -> None:
        shapes = (PrSection("Rule Illustration", "x"), PrSection("Module Relocations", "x"))
        flows = tuple(PrSection(f"New Behavior: {n}", "```\nx\n```") for n in range(4))
        draft = _draft(sections=(_SYMBOLS, *shapes, *flows))
        assert draft_problems(_facts(), draft) == [
            "at most one shape diagram (found 2)",
            "at most 3 behavior flows (found 4)",
            "sections out of order: behavior flows, then the shape diagram, then Changed Symbols",
        ]

    def test_vendor_name(self) -> None:
        assert draft_problems(_facts(), _draft(summary="Written with Claude."), level=1) == [
            "vendor name 'Claude' in the draft",
        ]


class TestDraftLevels:
    def test_level_one_is_plain(self) -> None:
        assert draft_problems(_facts(), _draft(), level=1) == []

    def test_level_one_rejects_sections(self) -> None:
        draft = _draft(sections=(_FLOW, _SYMBOLS))
        assert draft_problems(_facts(), draft, level=1) == [
            "sections are for levels 2 and 3; remove them or build with --level 2",
        ]

    @pytest.mark.parametrize("level", [2, 3])
    def test_visual_levels_need_sections(self, level: int) -> None:
        assert draft_problems(_facts(), _draft(), level=level) == [
            "a visual summary needs its sections (behavior flows or a shape diagram, Changed Symbols)",
        ]

    def test_default_level_is_two(self) -> None:
        draft = _draft(sections=(_FLOW, _SYMBOLS, PrSection("Legend", "x")))
        assert draft_problems(_facts(), draft, level=2) == draft_problems(_facts(), draft)
        assert DEFAULT_LEVEL == 2

    def test_level_three_allows_five_flows(self) -> None:
        flows = tuple(PrSection(f"New Behavior: {n}", "```\nx\n```") for n in range(5))
        assert draft_problems(_facts(), _draft(sections=(*flows, _SYMBOLS)), level=3) == []
        assert draft_problems(_facts(), _draft(sections=(*flows[:4], _SYMBOLS)), level=2) == [
            "at most 3 behavior flows (found 4)",
        ]

    def test_level_three_flow_limit(self) -> None:
        flows = tuple(PrSection(f"New Behavior: {n}", "```\nx\n```") for n in range(6))
        assert draft_problems(_facts(), _draft(sections=(*flows, _SYMBOLS)), level=3) == [
            "at most 5 behavior flows (found 6)",
        ]

    def test_level_three_allows_each_shape_once(self) -> None:
        shapes = tuple(
            PrSection(h, "x") for h in (
                "Module Relocations", "Symbol Relocations", "Call-Site Migration", "Rule Illustration",
                "Sequence Diagram", "Data Flow",
            )
        )
        assert draft_problems(_facts(), _draft(sections=(_FLOW, *shapes, _SYMBOLS)), level=3) == []

    def test_level_three_rejects_a_repeated_shape(self) -> None:
        shapes = (PrSection("Data Flow", "x"), PrSection("Data Flow", "y"))
        assert draft_problems(_facts(), _draft(sections=(_FLOW, *shapes, _SYMBOLS)), level=3) == [
            "shape diagram 'Data Flow' appears 2 times; use each at most once",
        ]

    @pytest.mark.parametrize("heading", ["Sequence Diagram", "Data Flow"])
    def test_new_shapes_are_level_three_only(self, heading: str) -> None:
        draft = _draft(sections=(_FLOW, PrSection(heading, "x"), _SYMBOLS))
        assert draft_problems(_facts(), draft, level=3) == []
        assert draft_problems(_facts(), draft, level=2) == [
            f"section '{heading}': unknown heading; use 'Behavior: <trigger>', 'New Behavior: <trigger>', "
            "a shape diagram name or 'Changed Symbols'",
        ]

    def test_level_three_keeps_section_order(self) -> None:
        draft = _draft(sections=(_SYMBOLS, PrSection("Data Flow", "x"), _FLOW))
        assert draft_problems(_facts(), draft, level=3) == [
            "sections out of order: behavior flows, then the shape diagram, then Changed Symbols",
        ]


class TestRenderSummary:
    def test_layout(self) -> None:
        text = render_summary(_facts(), _draft(sections=(PrSection("Changed Symbols", "```\nx\n```"),)))
        assert text.startswith(
            "# PR #7: Feature(a): `a` parameter\n\n**Branch:** 0007-demo\n**Base:** dev\n"
            "**Date:** 2026-10-10\n**Files Changed:** 3 (+43 / -1 lines, 1 relocated)\n\n"
            "## Summary\n\nAdds `a`.\n\n***Note:*** "
        )
        assert "\n## Changed Symbols\n\n```\nx\n```\n" in text
        assert "abc1234" not in text
        assert "<details><summary>Files Changed (2)</summary>" in text
        assert "| `src/pkg/a.py` | M | adds `a` |" in text
        assert "| `docs/PR_REVIEWS/0007_Demo.json` | A | (machine-generated artifact) |" in text
        assert "<details><summary>Relocated 1 files</summary>" in text
        assert "| `b.md` | `docs/old/` | `docs/new/` |" in text
        assert text.endswith("</details>\n")

    @pytest.mark.parametrize("working, line", [
        (True, "**Source:** local branch at `hhhhhhh`, plus uncommitted changes\n"),
        (False, "**Source:** local branch at `hhhhhhh`\n"),
    ])
    def test_local_capture_names_its_source(self, working: bool, line: str) -> None:
        text = render_summary(_facts(head_source="local", working_tree=working), _draft())
        assert f"**Date:** 2026-10-10\n{line}**Files Changed:** 3" in text

    @pytest.mark.parametrize("branch, label", [
        ("stacked", "local checkout `stacked`"),
        ("", "local detached checkout"),
        ("demo", "local branch"),
        (None, "local branch"),
    ])
    def test_local_capture_names_its_checkout(self, branch: Optional[str], label: str) -> None:
        facts = _facts(head_source="local", working_tree=True, local_branch=branch, head="demo")
        text = render_summary(facts, _draft())
        assert f"**Source:** {label} at `hhhhhhh`, plus uncommitted changes\n" in text

    def test_remote_capture_has_no_source_line(self) -> None:
        assert "**Source:**" not in render_summary(_facts(), _draft())

    def test_renamed_with_edits_shows_both_paths(self) -> None:
        facts = _facts(files=(PrFile("R", "n.py", "o.py", 1, 1),))
        text = render_summary(facts, _draft(descriptions={"n.py": "moved and edited"}))
        assert "| `o.py` → `n.py` | R | moved and edited |" in text
        assert "**Files Changed:** 1 (+1 / -1 lines)\n" in text

    def test_section_order(self) -> None:
        text = render_summary(_facts(), _draft(sections=(_FLOW, _SYMBOLS)))
        marks = [
            "## Summary", "***Note:***", "## New Behavior: append", "## Changed Symbols",
            "<summary>Files Changed (2)</summary>",
            "<summary>Relocated 1 files",
        ]
        positions = [text.index(mark) for mark in marks]
        assert positions == sorted(positions)

    def test_change_codes_and_no_commits_block(self) -> None:
        text = render_summary(_facts(), _draft())
        assert "<summary>Commits</summary>" not in text
        assert "abc1234 Feature(a): add a" not in text
        assert "\n\nChange codes: A = added, M = modified, D = deleted, R = renamed\n\n</p>" in text

    def test_cell_escapes_pipes_and_newlines(self) -> None:
        text = render_summary(_facts(), _draft(descriptions={"src/pkg/a.py": "adds a | b\n  and c"}))
        assert "| `src/pkg/a.py` | M | adds a \\| b and c |" in text

    def test_deleted_row(self) -> None:
        facts = _facts(files=(PrFile("D", "src/pkg/gone.py", None, 0, 9),))
        text = render_summary(facts, _draft(descriptions={"src/pkg/gone.py": "removes gone"}))
        assert "| `src/pkg/gone.py` | D | removes gone |" in text
