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
    AddTodoRequest,
    Closing,
    ResearchLevel,
    TodoHook,
)

__all__ = ["AGENT", "AddTodoRequest", "CATALOG_INIT", "CatalogRefused", "Closing", "HOOK_REL", "HOOK_VERSION",
           "ResearchLevel", "SESSION_ENV", "SESSION_KEY", "TodoHook", "arming_session", "catalog_file",
           "catalog_item", "clear_switch", "dispatch_row", "hook_catalog", "hook_switch", "read_hook_switch",
           "require_stable_ids", "todo_hook", "write_goal_switch", "write_hook_switch"]

AGENT = "harness:todo-editor"
CATALOG_INIT = "todo_sync.py init"
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
        lines.append(f"Hook: {request.hook.value}")
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


def todo_hook(closing: Closing, item: Dict[str, Any], now: Optional[float] = None) -> TodoHook:
    """The hook for ``closing`` tied to the catalog ``item`` (its id and title), started at ``now``."""
    start = time.time() if now is None else now
    title = (" ".join(str(item.get("title") or "").split()) or str(item["id"]))[:MAX_DESC_CHARS]
    return TodoHook(closed_by=closing, desc=title, start_time=start, todo_id=str(item["id"]))


def catalog_item(catalog: Dict[str, Any], todo_id: str) -> Optional[Dict[str, Any]]:
    """The item of the loaded ``catalog`` with ``todo_id``; None when it holds none."""
    for item in catalog.get("items", []):
        if isinstance(item, dict) and item.get("id") == todo_id:
            return item
    return None


class CatalogRefused(ValueError):
    """A TODO catalog a hook goal cannot read its item from; the message names the cause."""


def catalog_file(cfg: Any, who: str) -> Path:
    """The TODO catalog of ``cfg``; refuses a project without ``todo.folder`` or without a catalog yet.

    ``who`` names the command in the ``todo.folder`` refusal.
    """
    if not cfg.todo.enabled or cfg.todo.catalog is None:
        raise CatalogRefused(f"{who} needs todo.folder in .claude/harness.json")
    catalog = cfg.path(cfg.todo.catalog)
    if not catalog.is_file():
        raise CatalogRefused(f"no TODO catalog at {cfg.todo.catalog}; create it with {CATALOG_INIT}")
    return catalog


def require_stable_ids(data: Dict[str, Any], verb: str) -> None:
    """Refuse a loaded catalog that still holds rank-tied ``TODO-NNN`` ids."""
    from harness_lib.todo_sync import ids
    from harness_lib.todo_sync.errors import TodoSyncError
    try:
        ids.require_stable(data, verb)
    except TodoSyncError as exc:
        raise CatalogRefused(str(exc)) from exc


def hook_catalog(cfg: Any, who: str, verb: str) -> Dict[str, Any]:
    """The catalog a hook goal reads its item from, the one gate both switch writers share.

    Refuses (``CatalogRefused``) no ``todo.folder``, no catalog, a catalog that cannot be read or is not a
    JSON object, and rank-tied ids; ``who`` and ``verb`` name the caller in the messages.
    """
    catalog = catalog_file(cfg, who)
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise CatalogRefused(f"the TODO catalog at {cfg.todo.catalog} cannot be read") from None
    if not isinstance(data, dict):
        raise CatalogRefused(f"the TODO catalog at {cfg.todo.catalog} is not a JSON object")
    require_stable_ids(data, verb)
    return data


def clear_switch(path: Path) -> bool:
    """Remove the switch at ``path``, fired or not; whether one was there."""
    if not path.is_file():
        return False
    path.unlink()
    return True


def read_hook_switch(path: Path) -> Optional[Dict[str, Any]]:
    """The switch at ``path``; None when absent, unreadable or of another version."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != HOOK_VERSION:
        return None
    return data
