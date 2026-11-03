"""Contract test for the ``writing-docstrings`` skill: its SKILL.md, its ``harness:docstring-writer`` agent,
its convention reference and its models.

Labels, flags, thresholds and prompt lines are imported from ``writing_docstrings_models``, never copied: a
literal pinned here would drift from the module the commands read.
"""
from __future__ import annotations

from typing import List

import pytest
from pydantic import ValidationError

from harness_lib import writing_docstrings_api as api
from harness_lib import writing_docstrings_models as models
from harness_lib.project import plugin_root
from harness_lib.skill_parts import skill_parts

NAME = "writing-docstrings"
SKILL_DIR = plugin_root() / "skills" / NAME
SKILL = SKILL_DIR / "SKILL.md"
AGENT = plugin_root() / "agents" / "docstring-writer.md"
REFERENCE = SKILL_DIR / "docstring_format.md"
TIERS = ('sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" '
         '"${CLAUDE_PLUGIN_ROOT}/skills/writing-docstrings/commands/docstring_tiers.py"')
DISPATCH = ('sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" '
            '"${CLAUDE_PLUGIN_ROOT}/skills/writing-docstrings/commands/docstring_dispatch.py"')
REPLY_HEADINGS = ("Rewritten:", "Kept (in layout):", "Undocumented (rerun with --include-new):",
                  "Defects (not fixed):", "Check:")
PROBE_LINES = ("Probe tier: SUCCESS", "Probe tier: BLOCKED", "Probe edit: SUCCESS", "Probe edit: BLOCKED")


def _body() -> str:
    return skill_parts(SKILL)[1]


def _agent() -> str:
    assert AGENT.is_file(), f"{AGENT} is missing"
    return skill_parts(AGENT)[1]


def _first_offsets(text: str, labels: List[str]) -> List[int]:
    """Offset of the first backticked ``Label:`` of each label in ``text``; -1 when absent."""
    return [text.find(f"`{label}:`") for label in labels]


def test_frontmatter_names_the_skill_folder() -> None:
    keys = skill_parts(SKILL)[0]
    assert keys["name"].strip("\"'") == NAME


def test_description_is_filled() -> None:
    description = skill_parts(SKILL)[0].get("description", "").strip("\"'")
    assert description.startswith("Use when"), description


def test_body_runs_the_dispatch_driver_through_hpy() -> None:
    assert DISPATCH in _body()
    assert TIERS not in _body()


def test_body_names_every_dispatch_flag() -> None:
    body = _body()
    missing = [flag for flag in ("--include-new", "`-in`", "--parallel", "`-p`", "--clear-probe")
               if flag not in body]
    assert not missing, missing


def test_body_dispatches_the_docstring_writer() -> None:
    assert f'subagent_type="{models.AGENT}"' in _body()


def test_body_reads_the_convention_from_the_skill_dir() -> None:
    assert "${CLAUDE_SKILL_DIR}/docstring_format.md" in _body()
    assert REFERENCE.is_file()


def test_agent_frontmatter_names_its_tools() -> None:
    _agent()
    keys = skill_parts(AGENT)[0]
    assert keys["name"].strip("\"'") == models.AGENT.split(":", 1)[1]
    assert keys["model"].strip() == models.WORK_MODEL
    assert [tool.strip() for tool in keys["tools"].split(",")] == ["Read", "Edit", "Grep", "Bash"]


def test_agent_runs_the_tier_command_through_hpy() -> None:
    assert TIERS in _agent()


def test_agent_reads_the_convention_from_the_plugin_root() -> None:
    assert "${CLAUDE_PLUGIN_ROOT}/skills/writing-docstrings/docstring_format.md" in _agent()


def test_agent_compact_labels_appear_in_section_order() -> None:
    for text in (_agent(), REFERENCE.read_text(encoding="utf-8")):
        offsets = _first_offsets(text, list(models.SECTION_ORDER))
        assert -1 not in offsets, offsets
        assert offsets == sorted(offsets), offsets


def test_reference_names_every_known_label() -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    missing = [label for label in models.KNOWN_LABELS if f"{label}:" not in text]
    assert not missing, missing


def test_agent_names_every_flag() -> None:
    text = _agent()
    missing = [flag for flag in models.FLAG_NAMES if f"`{flag}`" not in text]
    assert not missing, missing


def test_agent_states_the_full_tier_threshold() -> None:
    assert f"over about {models.FULL_MIN_LINES} lines" in _agent()


def test_agent_names_the_prompt_lines() -> None:
    row = models.DispatchRow(model=models.WORK_MODEL, project_root="C:/p", new_docstrings=True, probe=True,
                             scopes=[models.FileScope(path="C:/p/a.py")])
    prefixes = [line.split(":", 1)[0] + ":" for line in row.text().splitlines()[1:]]
    text = _agent()
    missing = [prefix for prefix in prefixes if f"`{prefix}" not in text]
    assert not missing, missing


def test_agent_names_the_reply_headings_and_probe_lines() -> None:
    text = _agent()
    missing = [line for line in (*REPLY_HEADINGS, *PROBE_LINES) if line not in text]
    assert not missing, missing


def test_api_exports_existing_names() -> None:
    missing = [name for name in api.__all__ if not hasattr(api, name)]
    assert not missing, missing


def test_symbol_report_forbids_extra_keys() -> None:
    row = {"line": 1, "qualname": "f", "lines": 1, "forks": 0, "suggest": models.Tier.BRIEF,
           "current": models.Layout.NONE}
    assert models.SymbolReport.model_validate(row).row().endswith("current=none")
    with pytest.raises(ValidationError):
        models.SymbolReport.model_validate({**row, "unexpected": 1})
