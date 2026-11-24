"""Add Todo: the dispatch row ``add_todo.py row`` prints for the ``harness:todo-editor`` agent, and the hook
switch ``add_todo.py hook`` writes for the session-bookmark mod.

The row is the ``agent=`` line, then the prompt's header lines. The session appends the ``Note:`` and
``Context:`` lines, so the developer's text never passes through a command line.

The hook switch is ``<state_dir>/session-bookmark/hook.json``: ``{"version": 1, "hook": {<TodoHook>,
"goal"}, "session_id": <id or null>, "fired": null}``; a free-text goal (``add_note.py goal``, the bookmark
skill) stores ``{"goal", "start_time", "todo_id": null}`` as its hook. ``session_id`` is the arming
session's ``CLAUDE_CODE_SESSION_ID``, null when unset. The mod
(``plugins/session-bookmark/hooks/session_hook.ts``) runs ``/goal <goal>`` while ``fired`` is null, in the
arming session only (any session when ``session_id`` is null), then stamps ``fired``;
``tests/mods/test_session_bookmark_hook_contract.py`` pins the names both sides share.

``__all__`` is the surface ``skill_api.py`` binds for an api heredoc.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from harness_lib.add_todo_models import (
    MAX_DESC_CHARS,
    PENDING_DESC,
    AddTodoRequest,
    Closing,
    ResearchLevel,
    TodoHook,
)

__all__ = ["AGENT", "AddTodoRequest", "Closing", "HOOK_REL", "HOOK_VERSION", "ResearchLevel", "SESSION_ENV",
           "SESSION_KEY", "TodoHook", "arming_session", "catalog_item", "dispatch_row", "hook_switch",
           "read_hook_switch", "todo_hook", "write_goal_switch", "write_hook_switch"]

AGENT = "harness:todo-editor"
HOOK_REL = "session-bookmark/hook.json"
HOOK_VERSION = 1
SESSION_KEY = "session_id"
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"


def dispatch_row(request: AddTodoRequest, project_root: Path) -> List[str]:
    """The ``agent=`` line and the prompt header for ``request`` in the project at ``project_root``."""
    lines = [f"agent={AGENT} model={request.research.model}", "SKILL: add-todo", "Operation: add",
             f"Issue: {'yes' if request.issue else 'no'}", f"Research: {int(request.research)}",
             f"Project root: {Path(project_root).resolve().as_posix()}"]
    if request.hook is not None:
        lines.append(f"Hook: {request.hook.closed_by.value}")
    return lines


def arming_session(env: Mapping[str, str]) -> Optional[str]:
    """The session id ``env`` carries in ``SESSION_ENV``, stripped; None when unset or blank."""
    return env.get(SESSION_ENV, "").strip() or None


def _switch(hook: Dict[str, Any], session_id: Optional[str]) -> Dict[str, Any]:
    return {"version": HOOK_VERSION, "hook": hook, SESSION_KEY: session_id, "fired": None}


def hook_switch(hook: TodoHook, session_id: Optional[str] = None) -> Dict[str, Any]:
    """The switch file's content for ``hook``: armed (``fired`` null), the goal text precomputed, bound to
    ``session_id`` (any session when None)."""
    return _switch({**hook.model_dump(mode="json"), "goal": hook.goal()}, session_id)


def _write_switch(path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """Write ``data`` at ``path`` through a sibling temp file, replacing any earlier switch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return data


def write_hook_switch(path: Path, hook: TodoHook, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Write an armed switch for ``hook`` at ``path``, replacing any earlier one; returns what was written."""
    return _write_switch(path, hook_switch(hook, session_id))


def write_goal_switch(path: Path, goal: str, start_time: float,
                      session_id: Optional[str] = None) -> Dict[str, Any]:
    """Write an armed switch for a free-text ``goal`` tied to no item; returns what was written.

    The caller checks the goal (non-blank, at most ``MAX_GOAL_CHARS``); the mod folds and cuts it again.
    """
    return _write_switch(path, _switch({"goal": goal, "start_time": start_time, "todo_id": None}, session_id))


def todo_hook(closing: Closing, item: Optional[Dict[str, Any]] = None,
              now: Optional[float] = None) -> TodoHook:
    """The hook for ``closing``: tied to ``item`` (its id and title) once it exists.

    Without ``item`` it is the row-time hook: ``dispatch_row`` reads only its closing for the ``Hook:`` line,
    and it is never written as a switch.
    """
    start = time.time() if now is None else now
    if item is None:
        return TodoHook(closed_by=closing, desc=PENDING_DESC, start_time=start)
    title = (" ".join(str(item.get("title") or "").split()) or str(item["id"]))[:MAX_DESC_CHARS]
    return TodoHook(closed_by=closing, desc=title, start_time=start, todo_id=str(item["id"]))


def catalog_item(catalog: Dict[str, Any], todo_id: str) -> Optional[Dict[str, Any]]:
    """The item of the loaded ``catalog`` with ``todo_id``; None when it holds none."""
    for item in catalog.get("items", []):
        if isinstance(item, dict) and item.get("id") == todo_id:
            return item
    return None


def read_hook_switch(path: Path) -> Optional[Dict[str, Any]]:
    """The switch at ``path``; None when absent, unreadable or of another version."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != HOOK_VERSION:
        return None
    return data
