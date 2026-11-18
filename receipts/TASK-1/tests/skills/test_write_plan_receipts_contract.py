"""The write-plan skill states the receipts scheme: a frozen plan is never written during execution.

``record`` writes receipts; a change found mid-build goes to the plan's DesignEvolution through
``evolution_api.add`` (shown as a worked heredoc) and the receipt cites it; a lane takes its item text from
the plan JSON, and a lane that needs a deviation stops and reports it; the PIP is an HTML page opened from
disk. Plans frozen before receipts keep their sealed records, so the phrases are scoped to receipts plans.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def skill(plugin_root: Path) -> str:
    text = (plugin_root / "skills" / "write-plan" / "SKILL.md").read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", text)


def test_the_skill_says_nothing_writes_a_frozen_receipts_plan(skill: str) -> None:
    assert "nothing writes a receipts plan after its freeze" in skill.lower()
    assert "`record` writes receipts" in skill and "the seal is on the receipt" in skill.lower()


def test_the_skill_routes_a_mid_build_change_to_design_evolution(skill: str) -> None:
    assert "`evolution_api.add`" in skill and "DesignEvolution.json" in skill
    for flag in ("`--also", "`--substitute", "`--cite"):
        assert flag in skill


def test_the_skill_shows_a_design_change_built_through_the_models(skill: str) -> None:
    assert "from harness_lib.evolution_models import" in skill and "ChangeIssue(" in skill
    assert "evolution_api.next_id" in skill


def test_a_lane_takes_its_item_text_from_the_plan_json(skill: str) -> None:
    assert "plan_api.load" in skill and "item's PIP section" not in skill


def test_the_skill_keeps_refreeze_for_a_design_change_the_developer_asks_for(skill: str) -> None:
    assert "A refreeze is for a design change the developer asks for" in skill


def test_a_lane_that_needs_a_deviation_stops_and_reports_it(skill: str) -> None:
    assert "stops and reports" in skill and "--include-undeclared" in skill


def test_the_pip_is_an_html_page(skill: str) -> None:
    assert "_PIP.html" in skill and "live.js" in skill
    assert "The PIP markdown is rendered from the JSON" not in skill
    assert "open it from disk in a browser" in skill


def test_the_receipts_phrases_are_scoped_to_receipts_plans(skill: str) -> None:
    assert "Plans frozen before receipts keep the sealed scheme" in skill
    assert "A plan frozen before receipts keeps its markdown PIP" in skill
