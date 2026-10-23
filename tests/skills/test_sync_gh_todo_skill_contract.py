"""Guard test: the sync-gh-todo skill, the todo-editor agent and ``todo_sync.py`` agree.

The skill runs ``untracked`` and hands the listed issues to the agent; the agent owns the drafting and the
``add`` call. The files are prose, so the test parses the skill's own command lines with the driver's parser
and pins the names the skill and the agent must share.
"""
from __future__ import annotations

import importlib.util
import re
import shlex
from pathlib import Path
from typing import List

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_SKILL = _PLUGIN_ROOT / "skills" / "sync-gh-todo" / "SKILL.md"
_AGENT = _PLUGIN_ROOT / "agents" / "todo-editor.md"
_SCRIPT = _PLUGIN_ROOT / "scripts" / "todo_sync.py"
_LAUNCHER = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py"'
_REPLY_FIELDS = ("Operation", "Result", "Renumbered", "Prose fixed", "Added", "Stubs", "Resolved", "Close",
                 "Open", "Check")


def _text(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"missing {path}")
    return path.read_text(encoding="utf-8")


def _fenced_after(text: str, heading: str) -> List[str]:
    tail = text.split(heading, 1)[1]
    match = re.search(r"```\n(.*?)\n```", tail, re.DOTALL)
    assert match, f"no fenced block after {heading!r}"
    return match.group(1).splitlines()


def test_skill_names_itself_and_takes_no_arguments() -> None:
    block = re.match(r"^---\n(.*?)\n---\n", _text(_SKILL), re.DOTALL)
    assert block, "SKILL.md has no frontmatter"
    assert re.search(r"^name:\s*sync-gh-todo\s*$", block.group(1), re.MULTILINE)
    assert "argument-hint" not in block.group(1)


def test_skill_command_lines_parse() -> None:
    spec = importlib.util.spec_from_file_location("todo_sync_guard", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lines = re.findall(rf"^{re.escape(_LAUNCHER)} (.*)$", _text(_SKILL), re.MULTILINE)
    assert lines, "skill never runs todo_sync.py through the launcher"
    for line in lines:
        assert module._parser().parse_args(shlex.split(line)).command == "untracked"


def test_skill_dispatches_the_todo_editor_on_opus() -> None:
    body = _text(_SKILL)
    assert "harness:todo-editor" in body and "opus" in body
    prompt = _fenced_after(body, "with this prompt")
    assert [line.split(":", 1)[0] for line in prompt] == ["Operation", "Issues", "Project root", "Guidance"]


def test_skill_stops_when_nothing_is_untracked() -> None:
    assert "untracked: none" in _text(_SKILL)


def test_agent_documents_the_sync_operation() -> None:
    body = _text(_AGENT)
    description = body.split("---", 2)[1]
    assert "sync" in description
    section = body.split("## sync", 1)[1].split("\n## ", 1)[0]
    for needle in ("untracked.json", "add --spec", "--dry-run", "needs_decision", "one item per issue",
                   "unverified", "reviews", "review_errors", '"size"', '"consumers"'):
        assert needle in section, f"sync section never mentions {needle!r}"


def test_agent_reply_block_is_unchanged() -> None:
    lines = _fenced_after(_text(_AGENT), "## Reply")
    assert [line.split(":", 1)[0] for line in lines if ":" in line] == list(_REPLY_FIELDS)
