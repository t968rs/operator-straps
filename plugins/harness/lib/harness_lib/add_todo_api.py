"""Add Todo: the dispatch row ``add_todo.py row`` prints for the ``harness:todo-editor`` agent, and the hook
switch ``add_todo.py hook`` writes for the session-bookmark mod.

The row is the ``agent=`` line, then the prompt's header lines. The session appends the ``Note:`` and
``Context:`` lines, so the developer's text never passes through a command line.

The hook switch is ``<state_dir>/session-bookmark/hook.json``: ``{"version": 1, "hook": {<TodoHook>,
"goal"}, "fired": null}``. The mod (``plugins/session-bookmark/hooks/session_hook.ts``) runs ``/goal <goal>``
while ``fired`` is null, then stamps ``fired``; ``tests/mods/test_session_bookmark_hook_contract.py`` pins the
names both sides share.

``__all__`` is the surface ``skill_api.py`` binds for an api heredoc.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness_lib.add_todo_models import AddTodoRequest, Closing, ResearchLevel, TodoHook

__all__ = ["AGENT", "AddTodoRequest", "Closing", "HOOK_REL", "HOOK_VERSION", "ResearchLevel", "TodoHook",
           "dispatch_row", "hook_switch", "read_hook_switch", "write_hook_switch"]

AGENT = "harness:todo-editor"
HOOK_REL = "session-bookmark/hook.json"
HOOK_VERSION = 1


def dispatch_row(request: AddTodoRequest, project_root: Path) -> List[str]:
    """The ``agent=`` line and the prompt header for ``request`` in the project at ``project_root``."""
    lines = [f"agent={AGENT} model={request.research.model}", "SKILL: add-todo", "Operation: add",
             f"Issue: {'yes' if request.issue else 'no'}", f"Research: {int(request.research)}",
             f"Project root: {Path(project_root).resolve().as_posix()}"]
    if request.hook is not None:
        lines.append(f"Hook: {request.hook.closed_by.value}")
    return lines


def hook_switch(hook: TodoHook) -> Dict[str, Any]:
    """The switch file's content for ``hook``: armed (``fired`` null), the goal text precomputed."""
    return {"version": HOOK_VERSION, "hook": {**hook.model_dump(mode="json"), "goal": hook.goal()},
            "fired": None}


def write_hook_switch(path: Path, hook: TodoHook) -> Dict[str, Any]:
    """Write an armed switch for ``hook`` at ``path``, replacing any earlier one; returns what was written."""
    data = hook_switch(hook)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return data


def read_hook_switch(path: Path) -> Optional[Dict[str, Any]]:
    """The switch at ``path``; None when absent, unreadable or of another version."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != HOOK_VERSION:
        return None
    return data
