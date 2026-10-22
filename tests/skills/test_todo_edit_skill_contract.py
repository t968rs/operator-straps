"""Guard test: the todo-edit skill and the todo-editor agent agree on `--delete-retired` and the reply block.

The skill parses the flag and passes it as a prompt line; the agent owns the deletion gate and the report.
Both files are prose, so the test pins the names the two sides must share.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_SKILL = _PLUGIN_ROOT / "skills" / "todo-edit" / "SKILL.md"
_AGENT = _PLUGIN_ROOT / "agents" / "todo-editor.md"

_REPLY_FIELDS = ("Operation", "Result", "Renumbered", "Prose fixed", "Added", "Stubs", "Resolved", "Close",
                 "Open", "Check")


def _text(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"missing {path}")
    return path.read_text(encoding="utf-8")


def _fenced_after(text: str, heading: str) -> List[str]:
    """Lines of the first fenced block that follows ``heading``."""
    tail = text.split(heading, 1)[1]
    match = re.search(r"```\n(.*?)\n```", tail, re.DOTALL)
    assert match, f"no fenced block after {heading!r}"
    return match.group(1).splitlines()


def test_argument_hint_lists_the_flag() -> None:
    hint = re.search(r"^argument-hint:\s*(.+)$", _text(_SKILL), re.MULTILINE)
    assert hint, "SKILL.md has no argument-hint"
    assert "--delete-retired" in hint.group(1)


def test_skill_limits_the_flag_to_retire() -> None:
    body = _text(_SKILL)
    assert re.search(r"--delete-retired[^\n]*--retire|--retire[^\n]*--delete-retired", body)
    assert "print the `argument-hint`" in body, "an unusable flag combination must stop at the hint"


def test_dispatch_prompt_carries_the_flag_line() -> None:
    skill_lines = _fenced_after(_text(_SKILL), "The prompt is this block")
    assert any(line.startswith("Delete retired:") for line in skill_lines)
    assert "Delete retired:" in _text(_AGENT)


def test_agent_reply_block_has_every_field() -> None:
    lines = _fenced_after(_text(_AGENT), "## Reply")
    names = [line.split(":", 1)[0] for line in lines if ":" in line]
    assert names == list(_REPLY_FIELDS)


def test_agent_gates_stub_deletion_on_run_evidence() -> None:
    body = _text(_AGENT)
    section = body.split("## delete-retired", 1)[1].split("\n## ", 1)[0]
    for needle in ("FULLY_IMPLEMENTED", "stub_path", "null", "kept", "ran", "log --oneline"):
        assert needle in section, f"delete-retired section never mentions {needle!r}"
