"""The PIP ``plan_render`` writes from a plan: sections the plan rules find, boxes that follow status."""
from __future__ import annotations

from typing import Any, Dict

from harness_lib import plan_render as pr
from harness_lib.todo_sync.pip_sections import find_section, parse_pip


def sample_plan(status: str = "PENDING") -> Dict[str, Any]:
    return {
        "plan_id": "0003", "plan_created": "2026-10-28", "execution_model": "serial",
        "source_document": "docs/specs/split.md", "branch": "feat-x", "base_branch": "main",
        "base_commit": "abcdef1" + "0" * 33,
        "decisions": [{"id": "D1", "question": "Split or keep?", "chosen": "split",
                       "rationale": "smaller files",
                       "options": [{"id": "split", "summary": "two modules"},
                                   {"id": "keep", "summary": "one module"}]},
                      {"id": "D2", "question": "Rename now?", "chosen": None,
                       "options": [{"id": "now", "summary": "now"}, {"id": "later", "summary": "later"}]}],
        "values": [{"name": "rows", "value": "6 | 7", "source": "spec Section 2", "assumes": ["split"]}],
        "sweeps": [{"id": "S1", "pattern": "old_name", "hits": {"src/user.py": "rewrite"}}],
        "items": [
            {"id": "TASK-1", "title": "Split the module", "action": "Move the readers.", "status": status,
             "evidence": "not started", "files": ["src/a.py"], "model": "haiku",
             "anchors": [{"at": "src/a.py:1-2", "expect": "def read"}],
             "commands": [{"run": "python -m pytest tests/test_a.py -q", "expect": "1 passed"}],
             "tests": [{"node": "tests/test_a.py::test_read", "red": "ImportError"}]},
            {"id": "TASK-10", "title": "Docs", "action": "Document it.", "status": "PENDING",
             "evidence": "not started", "files": ["docs/a.md"], "dependencies": ["TASK-1"]},
        ],
    }


def test_each_item_has_a_section_the_plan_rules_find() -> None:
    doc = parse_pip(pr.render_pip(sample_plan(), "0003_Split_ActionPlan.json"))
    first, tenth = find_section(doc, "TASK-1"), find_section(doc, "TASK-10")
    assert first is not None and first.heading.text == "TASK-1: Split the module"
    assert tenth is not None and tenth.heading.text == "TASK-10: Docs"


def test_an_open_item_has_one_open_box_per_step() -> None:
    doc = parse_pip(pr.render_pip(sample_plan(), "p.json"))
    section = find_section(doc, "TASK-1")
    assert section is not None and len(section.boxes) == 3 and len(section.unchecked) == 3


def test_a_done_item_has_every_box_checked() -> None:
    doc = parse_pip(pr.render_pip(sample_plan("COMPLETE"), "p.json"))
    section = find_section(doc, "TASK-1")
    assert section is not None and section.boxes and not section.unchecked


def test_an_item_without_tests_or_commands_still_has_its_record_box() -> None:
    doc = parse_pip(pr.render_pip(sample_plan(), "p.json"))
    section = find_section(doc, "TASK-10")
    assert section is not None and len(section.unchecked) == 1


def test_the_header_names_the_source_plan_and_the_base() -> None:
    text = pr.render_pip(sample_plan(), "0003_Split_ActionPlan.json")
    assert text.startswith("# Plan 0003: Split\n")
    assert pr.render_pip(sample_plan(), "p.json").startswith("# Plan 0003\n")
    assert "`0003_Split_ActionPlan.json`" in text
    assert "**Base commit:** `abcdef1`" in text
    assert "**Frozen:** no" in text


def test_decisions_show_the_choice_and_open_questions() -> None:
    text = pr.render_pip(sample_plan(), "p.json")
    assert "- **D1** Split or keep? Chosen: `split` (two modules). Rejected: `keep` (one module)." in text
    assert "- **D2** Rename now? **Open.** Options: `now` (now), `later` (later)." in text


def test_a_pipe_in_a_table_cell_is_escaped() -> None:
    assert "| rows | 6 \\| 7 | spec Section 2 | split |" in pr.render_pip(sample_plan(), "p.json")


def test_a_code_span_holding_a_backtick_uses_a_longer_fence() -> None:
    assert pr.code("a`b") == "`` a`b ``"
    assert pr.code("ab") == "`ab`"


def test_rendering_is_deterministic() -> None:
    assert pr.render_pip(sample_plan(), "p.json") == pr.render_pip(sample_plan(), "p.json")
