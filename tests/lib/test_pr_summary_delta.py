"""Behavioral tests for the pr-sum delta table and the shared machine-generated rule of pr_summary.

``PrFile.artifact`` follows ``harness_lib.diff_delta`` (the project's exclusions file, the harness output
patterns and the Artifact commit bucket); ``PrFacts.delta`` is the filtered ``DiffDelta`` of every file; the
Source / Machine-generated / Total table replaces the artifact Note whenever a file is excluded. Every test
activates a throwaway project from ``make_project``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from harness_lib import pr_summary
from harness_lib.config import activate, load_config
from harness_lib.pr_summary import PrDraft, PrFacts, PrFile, delta_table, render_summary

_EXCLUSIONS = {"exclusions": [{"pattern": "gen/*", "reason": "generated report"}]}
_TABLE = "\n".join([
    "| Delta             | Files |  + | - | Net |",
    "|-------------------|------:|---:|--:|----:|",
    "| Source            |     1 |  3 | 1 |  +2 |",
    "| Machine-generated |     1 | 40 | 0 | +40 |",
    "| Total             |     2 | 43 | 1 | +42 |",
])


@pytest.fixture(autouse=True)
def _project(make_project: Callable[..., Path]) -> Path:
    """A project whose exclusions file names ``gen/*``, activated for the test."""
    root = make_project(config={"exclusions": "config/ex.json"}, files={"config/ex.json": _EXCLUSIONS})
    activate(load_config(root))
    return root


def _facts(*files: PrFile) -> PrFacts:
    chosen = files or (PrFile("M", "src/pkg/a.py", None, 3, 1), PrFile("A", "gen/out.json", None, 40, 0))
    return PrFacts(number=7, pr_title="t", head="7-x", base="main", head_sha="h" * 40, merge_base="m" * 40,
                   date="2026-11-06", commits=("abc1234 Fix: x",), files=chosen)


def _draft() -> PrDraft:
    return PrDraft(title="Fix: `a` change", summary="Changes `a`.",
                   descriptions={"src/pkg/a.py": "changes `a`"})


def test_artifact_follows_the_exclusions_file() -> None:
    assert PrFile("A", "gen/out.json", None, 1, 0).artifact
    assert PrFile("A", "docs/PR_REVIEWS/0001_x.json", None, 1, 0).artifact
    assert not PrFile("M", "src/pkg/a.py", None, 1, 0).artifact
    assert _facts().described == ("src/pkg/a.py",)


def test_facts_delta_filters_machine_generated_files() -> None:
    delta = _facts().delta
    assert (delta.adds, delta.subs, delta.files, delta.excluded) == (3, 1, 1, ("gen/out.json",))
    assert delta.full is not None and (delta.full.adds, delta.full.subs, delta.full.files) == (43, 1, 2)


def test_delta_table_layout() -> None:
    assert delta_table(_facts()) == _TABLE


def test_delta_table_absent_without_excluded_files() -> None:
    assert delta_table(_facts(PrFile("M", "src/pkg/a.py", None, 3, 1))) is None


def test_delta_table_shown_for_any_excluded_file() -> None:
    files = (PrFile("M", "src/pkg/a.py", None, 300, 100), PrFile("A", "gen/o.json", None, 1, 0))
    table = delta_table(_facts(*files))
    assert table is not None and "| Machine-generated |" in table


def test_render_places_the_table_after_the_summary() -> None:
    text = render_summary(_facts(), _draft())
    assert "***Note:***" not in text
    assert f"## Summary\n\nChanges `a`.\n\n{_TABLE}\n" in text
    assert "**Files Changed:** 2 (+43 / -1 lines)" in text


def test_artifact_note_is_gone() -> None:
    assert not hasattr(pr_summary, "artifact_note")
