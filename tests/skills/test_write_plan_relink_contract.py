"""The write-plan skill and its README state the relink base check (plan 2024 TASK-3, issue 313).

The SKILL.md **Relink.** paragraph says ``relink`` runs the plan's anchors and sweeps at the candidate base
and refuses with ``at base <sha7>:`` problem lines, and that a base squashed inside another pull request has
no counterpart on HEAD's history, so its ``off-history:`` warning is the end state. The skill README says
the same in one sentence.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def relink_step(plugin_root: Path) -> str:
    skill = _flat(plugin_root / "skills" / "write-plan" / "SKILL.md")
    return skill.split("**Relink.**", 1)[1].split("**Archive.**", 1)[0]


def test_the_relink_paragraph_states_the_base_check(relink_step: str) -> None:
    assert "anchors and sweeps" in relink_step
    assert "`at base <sha7>:`" in relink_step


def test_the_relink_paragraph_names_the_off_history_end_state(relink_step: str) -> None:
    assert "squashed inside another pull request" in relink_step
    assert "the `off-history:` warning is then the correct end state" in relink_step


def test_the_relink_paragraph_orders_a_claim_fix_before_the_refreeze(relink_step: str) -> None:
    assert ("correct the anchors and sweeps for the candidate base with `write`, rerun the relink, "
            "then `freeze --refreeze`") in relink_step


def test_the_skill_readme_states_the_relink_refusal(plugin_root: Path) -> None:
    text = _flat(plugin_root / "skills" / "write-plan" / "README.md")
    assert "refuses a base where the plan's anchors or sweeps fail" in text
    assert "stays off-history" in text
