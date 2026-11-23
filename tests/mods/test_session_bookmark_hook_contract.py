"""Pin the hook switch ``add_todo.py hook`` writes to the names the session-bookmark mod reads.

The driver (``plugins/harness/scripts/add_todo.py``, through ``harness_lib.add_todo_api``) writes
``<state_dir>/session-bookmark/hook.json``; the mod (``plugins/session-bookmark/hooks/session_hook.ts``) runs
``/goal`` from it once and stamps ``fired``. An installed mod cannot import the harness plugin, so
``session_hook.ts`` copies the path, version, goal limit and the ``fired`` key. This test fails when one side
changes without the other.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_lib import add_todo_api
from harness_lib.add_todo_models import MAX_GOAL_CHARS, Closing, TodoHook
from mods._mods_helpers import ts_number, ts_string

_HOOK_TS_REL = "plugins/session-bookmark/hooks/session_hook.ts"
_REGISTER_TS_REL = "plugins/session-bookmark/hooks/register.ts"


@pytest.fixture(scope="module")
def hook_ts(repo_root: Path) -> str:
    return (repo_root / _HOOK_TS_REL).read_text(encoding="utf-8")


def test_hook_path_matches(hook_ts: str) -> None:
    assert ts_string(hook_ts, "HOOK_PATH") == add_todo_api.HOOK_REL


def test_schema_version_matches(hook_ts: str) -> None:
    assert ts_number(hook_ts, "HOOK_SCHEMA_VERSION") == add_todo_api.HOOK_VERSION


def test_goal_limit_matches(hook_ts: str) -> None:
    assert ts_number(hook_ts, "MAX_GOAL_CHARS") == MAX_GOAL_CHARS


def test_an_armed_switch_has_the_keys_the_mod_reads(hook_ts: str, tmp_path: Path) -> None:
    hook = TodoHook(closed_by=Closing.RETIRED, desc="catalog item model", start_time=1.5, todo_id="todo-af2e")
    path = tmp_path / add_todo_api.HOOK_REL
    add_todo_api.write_hook_switch(path, hook)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored[ts_string(hook_ts, "FIRED_KEY")] is None
    assert {"goal", "todo_id", "start_time"} <= set(stored["hook"])
    for key in ("data.hook.goal", "data.hook.todo_id", "data.hook.start_time"):
        assert key in hook_ts


def test_a_free_text_goal_switch_has_the_keys_the_mod_reads(hook_ts: str, tmp_path: Path) -> None:
    path = tmp_path / add_todo_api.HOOK_REL
    add_todo_api.write_goal_switch(path, "the tests in test_x.py pass", 2.5)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["version"] == add_todo_api.HOOK_VERSION and stored[ts_string(hook_ts, "FIRED_KEY")] is None
    assert stored["hook"] == {"goal": "the tests in test_x.py pass", "start_time": 2.5, "todo_id": None}


def test_the_mod_registers_the_session_hook(repo_root: Path) -> None:
    register_ts = (repo_root / _REGISTER_TS_REL).read_text(encoding="utf-8")
    assert "registerSessionHook(on)" in register_ts
