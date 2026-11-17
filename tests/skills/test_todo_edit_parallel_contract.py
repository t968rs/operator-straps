"""Guard test: the todo-edit skill splits several items and queues field updates in parallel.

``--split`` takes one or more ids and ``--update`` takes one or more ids plus guidance; either dispatches one
``harness:todo-editor`` agent per id, all in one message. The agent's ``update`` operation queues its field
updates with ``inbox put --update`` and never writes the catalog, and the skill drains the inbox once after
every update agent has returned. Both files are prose, so the test pins the names the two sides share.
"""
from __future__ import annotations

import importlib.util
import re
import shlex
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_SKILL = _PLUGIN_ROOT / "skills" / "todo-edit" / "SKILL.md"
_AGENT = _PLUGIN_ROOT / "agents" / "todo-editor.md"
_SCRIPT = _PLUGIN_ROOT / "scripts" / "todo_sync.py"
_LAUNCHER = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py"'


@pytest.fixture(scope="module")
def parser():
    spec = importlib.util.spec_from_file_location("todo_edit_parallel_guard", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._parser()


def _skill() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _skill_section(heading: str) -> str:
    body = _skill()
    assert heading in body, f"no {heading!r} section"
    return body.split(heading, 1)[1].split("\n## ", 1)[0]


def _agent_section(name: str) -> str:
    body = _AGENT.read_text(encoding="utf-8")
    assert f"\n## {name}\n" in body, f"todo-editor.md has no {name} section"
    return body.split(f"\n## {name}\n", 1)[1].split("\n## ", 1)[0]


def test_argument_hint_takes_several_split_ids_and_an_update() -> None:
    hint = re.search(r"^argument-hint:\s*(.+)$", _skill(), re.MULTILINE)
    assert hint, "SKILL.md has no argument-hint"
    assert "--split ID[, ID ...]" in hint.group(1)
    assert "--update ID[, ID ...]" in hint.group(1)


def test_update_without_guidance_stops_at_the_hint() -> None:
    assert "`--update` with no guidance" in _skill_section("## Step 1")


def test_split_and_update_dispatch_one_agent_per_id_in_one_message() -> None:
    step = _skill_section("## Step 2")
    assert "one `Agent` call per id" in step
    assert "in one message" in step
    assert "Operation: <retire | split | refresh | update>" in step


def test_the_skill_drains_the_inbox_once_after_the_update_agents(parser) -> None:
    body = _skill()
    drain = re.search(rf"^{re.escape(_LAUNCHER)} (add --inbox)\s*$", body, re.MULTILINE)
    assert drain, "the skill never drains the inbox through the launcher"
    assert parser.parse_args(shlex.split(drain.group(1))).inbox
    assert body.index("harness:todo-editor") < drain.start()
    assert "inbox: empty" in body


def test_the_agent_queues_updates_and_holds_no_lease() -> None:
    update = _agent_section("update")
    assert "TS inbox put --update --spec <path>" in update
    assert "todo-sync/update-<stamp>-<rand>.json" in update
    assert "TS lease acquire" not in update
    assert '"updates"' in update and '"fields"' in update


def test_the_agent_names_the_fields_an_update_may_set() -> None:
    update = _agent_section("update")
    for field in ("`summary`", "`files`", "`code_snippet`", "`proposed_change`", "`severity`", "`loe`"):
        assert field in update, field
    assert "`rank`" in update, "the section names a field the script refuses"


def test_the_agent_reports_queued_updates_under_added() -> None:
    update = _agent_section("update")
    assert "queued update: <id> (<fields>)" in update
    reply = _AGENT.read_text(encoding="utf-8").split("\n## Reply\n", 1)[1]
    assert "queued update" in reply
