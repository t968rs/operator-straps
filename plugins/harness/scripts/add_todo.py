#!/usr/bin/env python3
"""add-todo driver: print the ``harness:todo-editor`` dispatch row for one note, and arm the session hook.

``row [--issue] [-r|--research 0-3] [--hook retired|committed|developer]``
    Print the ``agent=`` line (the model the research level picks) and the prompt header: ``SKILL``,
    ``Operation: add``, ``Issue``, ``Research`` and ``Project root``, plus ``Hook: <closing>`` with
    ``--hook``. The session appends ``Note:`` and ``Context:``; the note never reaches this command. Refuses,
    with one ``problem:`` line on stderr and exit 1, a project without ``todo.folder``, one whose catalog does
    not exist yet (``todo_sync.py init`` creates it) and one that still holds rank-tied ``TODO-NNN`` ids
    (``migrate-ids`` switches it). A research level outside 0-3 is an argument error, exit 2.

``hook --todo <id> --closed-by retired|committed|developer``
    Arm the hook switch (``<state_dir>/session-bookmark/hook.json``) for a catalog item: the item's title is
    the description, the goal names the item and its closing clause. The session-bookmark mod runs
    ``/goal <goal>`` when the current main-loop turn ends. Prints
    ``hook: armed <id> (<closing>); goal: <goal>``. An id the catalog does not hold is refused (exit 1).

``hook --clear``
    Remove the switch, fired or not; prints ``hook: cleared`` or ``hook: none``. Needs no ``todo.folder`` or
    catalog, so it also clears a free-text switch. The goal itself, once set, ends with ``/goal clear``.

``--repo`` (default: the working directory) names a directory inside the project.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib.add_todo_api import (  # noqa: E402
    HOOK_REL,
    catalog_item,
    dispatch_row,
    todo_hook,
    write_hook_switch,
)
from harness_lib.add_todo_models import AddTodoRequest, Closing, ResearchLevel  # noqa: E402
from harness_lib.config import ConfigError, HarnessConfig, activate, load_config  # noqa: E402
from harness_lib.project import project_root  # noqa: E402
from harness_lib.todo_sync import ids  # noqa: E402
from harness_lib.todo_sync.errors import TodoSyncError  # noqa: E402

INIT = "todo_sync.py init"
CLOSINGS = [c.value for c in Closing]


class Refused(Exception):
    """A refused run; the message is the ``problem:`` text."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print the harness:todo-editor dispatch row for add-todo.")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Directory inside the project.")
    sub = parser.add_subparsers(dest="command", required=True)
    row = sub.add_parser("row", help="Print the dispatch row.")
    row.add_argument("--issue", action="store_true", help="File a GitHub issue for the item.")
    row.add_argument("-r", "--research", type=int, choices=[int(level) for level in ResearchLevel],
                     default=int(ResearchLevel.NONE), help="Research level: 0 (none) to 3 (exhaustive).")
    row.add_argument("--hook", choices=CLOSINGS,
                     help="Make the added item the session goal, closed this way.")
    hook = sub.add_parser("hook", help="Arm or clear the session hook switch.")
    hook.add_argument("--todo", help="The catalog id the goal names.")
    hook.add_argument("--closed-by", choices=CLOSINGS, help="What closes the goal.")
    hook.add_argument("--clear", action="store_true", help="Remove the switch.")
    return parser


def _ready(cfg: HarnessConfig) -> Path:
    """The catalog path; refuses a project the agent could not add to: no TODO folder, or no catalog yet."""
    if not cfg.todo.enabled or cfg.todo.catalog is None:
        raise Refused("add-todo needs todo.folder in .claude/harness.json")
    catalog = cfg.path(cfg.todo.catalog)
    if not catalog.is_file():
        raise Refused(f"no TODO catalog at {cfg.todo.catalog}; create it with {INIT}")
    _refuse_legacy(catalog)
    return catalog


def _load(catalog: Path) -> Optional[Dict[str, Any]]:
    """The catalog's JSON object; None when unreadable or not an object."""
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _refuse_legacy(catalog: Path) -> None:
    """Refuse a catalog that still holds TODO-NNN ids; an unreadable catalog is left to the later add."""
    data = _load(catalog)
    if data is None:
        return
    try:
        ids.require_stable(data, "add-todo")
    except TodoSyncError as exc:
        raise Refused(str(exc)) from exc


def _item(catalog: Path, todo_id: str) -> Dict[str, Any]:
    """The catalog item with ``todo_id``; refuses an id the catalog does not hold."""
    item = catalog_item(_load(catalog) or {}, todo_id)
    if item is None:
        raise Refused(f"hook: no catalog item {todo_id}")
    return item


def _switch_path(cfg: HarnessConfig) -> Path:
    """The hook switch file under ``state_dir``."""
    return cfg.path(cfg.state_dir) / HOOK_REL


def _clear(cfg: HarnessConfig) -> str:
    """Remove the switch, fired or not; needs no TODO catalog. Returns the line to print."""
    path = _switch_path(cfg)
    if not path.is_file():
        return "hook: none"
    path.unlink()
    return "hook: cleared"


def _hook(cfg: HarnessConfig, catalog: Path, args: argparse.Namespace) -> str:
    """Arm the switch for a catalog item; returns the line to print."""
    if not args.todo or not args.closed_by:
        raise Refused("hook needs --todo <id> and --closed-by, or --clear")
    hook = todo_hook(Closing(args.closed_by), _item(catalog, args.todo))
    write_hook_switch(_switch_path(cfg), hook)
    return f"hook: armed {hook.todo_id} ({hook.closed_by.value}); goal: {hook.goal()}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
    args = _parser().parse_args(argv)
    try:
        cfg = activate(load_config(project_root(args.repo)))
        if args.command == "hook" and args.clear:
            print(_clear(cfg))
            return 0
        catalog = _ready(cfg)
        if args.command == "hook":
            print(_hook(cfg, catalog, args))
            return 0
    except (ConfigError, Refused, OSError, ValueError) as exc:
        print(f"problem: {' '.join(str(exc).split())}", file=sys.stderr)
        return 1
    hook = None if args.hook is None else todo_hook(Closing(args.hook))
    request = AddTodoRequest(issue=args.issue, research=ResearchLevel(args.research), hook=hook)
    print("\n".join(dispatch_row(request, cfg.project_root)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
