"""The harness routes new work through ``harness:specsheet-lite`` before ``harness:write-plan``.

The rules name the spec sheet as the design step, and write-plan's start step names the sheet as its spec.
"""
from __future__ import annotations

import re

from conftest import PLUGIN_ROOT

RULES = PLUGIN_ROOT / "rules" / "HARNESS_RULES.md"
WRITE_PLAN = PLUGIN_ROOT / "skills" / "write-plan" / "SKILL.md"


def _stage_lines() -> list:
    text = RULES.read_text(encoding="utf-8")
    section = text.split("## Skill invocation at development stages", 1)[1].split("\n## ", 1)[0]
    return [line for line in section.splitlines() if line.startswith("- **")]


def test_rules_name_the_spec_sheet_as_the_design_step() -> None:
    lines = [line for line in _stage_lines() if "harness:specsheet-lite" in line]
    assert len(lines) == 1
    assert re.search(r"harness:specsheet-lite.*harness:write-plan", lines[0])


def test_the_design_step_comes_before_creating_plans() -> None:
    lines = _stage_lines()
    design = [n for n, line in enumerate(lines) if "harness:specsheet-lite" in line]
    plans = [n for n, line in enumerate(lines) if line.startswith("- **Creating plans:**")]
    assert design and plans and design[0] < plans[0]
    assert "harness:write-plan" in lines[plans[0]]


def test_write_plan_start_names_the_spec_sheet() -> None:
    text = WRITE_PLAN.read_text(encoding="utf-8")
    start = text.split("1. **Start.**", 1)[1].split("\n2. ", 1)[0]
    assert "harness:specsheet-lite" in start
