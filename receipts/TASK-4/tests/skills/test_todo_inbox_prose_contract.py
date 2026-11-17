"""Guard test: the todo-editor agent and the add-todo skill follow the inbox and lease flow.

Add and sync runs queue each drafted item with ``inbox put`` and never write the catalog; the dispatching
skills drain the inbox once the agent returns, so the harness works without the todo-watch mod. Retire and
refresh runs hold a lease from start to reply, a split from its dry run to its reply. Every
``TS <subcommand>`` the agent names parses with the driver's own parser.
"""
from __future__ import annotations

import importlib.util
import re
import shlex
from pathlib import Path
from typing import List

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_AGENT = _PLUGIN_ROOT / "agents" / "todo-editor.md"
_ADD_SKILL = _PLUGIN_ROOT / "skills" / "add-todo" / "SKILL.md"
_SCRIPT = _PLUGIN_ROOT / "scripts" / "todo_sync.py"
_LAUNCHER = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py"'


@pytest.fixture(scope="module")
def parser():
    spec = importlib.util.spec_from_file_location("todo_sync_prose_guard", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._parser()


def _section(name: str) -> str:
    body = _AGENT.read_text(encoding="utf-8")
    return body.split(f"\n## {name}\n", 1)[1].split("\n## ", 1)[0]


def _ts_commands(text: str) -> List[str]:
    return re.findall(r"`TS ([^`]+)`", text)


def test_every_ts_command_in_the_agent_parses(parser) -> None:
    commands = _ts_commands(_AGENT.read_text(encoding="utf-8"))
    assert commands
    for command in commands:
        try:
            parser.parse_args(shlex.split(command))
        except SystemExit:
            raise AssertionError(f"todo_sync.py rejects `TS {command}`") from None


@pytest.mark.parametrize("name", ["sync", "add"])
def test_add_and_sync_queue_items_and_never_write_the_catalog(name: str) -> None:
    section = _section(name)
    assert "TS inbox put --spec" in section
    assert "TS add --spec" not in section
    assert "queued" in section


@pytest.mark.parametrize("name", ["sync", "add"])
def test_each_run_stages_its_spec_at_a_path_of_its_own(name: str) -> None:
    section = _section(name)
    assert "todo-sync/add-<stamp>-<rand>.json" in section
    assert "todo-sync/add.json" not in section


def test_the_add_operation_files_the_issue_through_the_inbox() -> None:
    assert "TS inbox put --spec <path> --file-issue" in _section("add")


@pytest.mark.parametrize("name", ["retire", "split", "refresh"])
def test_structural_runs_hold_a_lease(name: str) -> None:
    section = _section(name)
    assert "TS lease acquire --owner" in section
    assert "--lease <token>" in section


def test_finish_releases_the_lease_before_the_reply() -> None:
    finish = _section("finish")
    assert "TS lease release <token>" in finish


def test_the_add_skill_drains_the_inbox_after_the_agent(parser) -> None:
    body = _ADD_SKILL.read_text(encoding="utf-8")
    lines = re.findall(rf"^{re.escape(_LAUNCHER)} (.*)$", body, re.MULTILINE)
    drains = [line for line in lines if parser.parse_args(shlex.split(line)).command == "add"]
    assert drains and all(parser.parse_args(shlex.split(line)).inbox for line in drains)
    assert "inbox: empty" in body
    drain = re.search(rf"^{re.escape(_LAUNCHER)} add --inbox\s*$", body, re.MULTILINE)
    assert drain, "the add skill never drains the inbox through the launcher"
    assert body.index("harness:todo-editor") < drain.start(), "the drain runs before the agent is dispatched"
