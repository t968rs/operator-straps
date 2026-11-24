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
    ``/goal <goal>`` when the current main-loop turn ends, in the arming session only: the switch records
    ``CLAUDE_CODE_SESSION_ID`` (any session when unset). Prints
    ``hook: armed <id> (<closing>); goal: <goal>``. An id the catalog does not hold, and a catalog that
    cannot be read or is not a JSON object, is refused (exit 1); ``add_note.py goal --todo`` shares the gate
    (``add_todo_api.hook_catalog``).

``hook --clear``
    Remove the switch, fired or not; prints ``hook: cleared`` or ``hook: none``. Needs no ``todo.folder`` or
    catalog, so it also clears a free-text switch. The goal itself, once set, ends with ``/goal clear``.
    ``--clear`` with ``--todo`` or ``--closed-by`` is refused (exit 1) and leaves the switch in place.

``--repo`` (default: the working directory) names a directory inside the project.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib.add_todo_api import (  # noqa: E402
    HOOK_REL,
    arming_session,
    catalog_file,
    catalog_item,
    clear_switch,
    dispatch_row,
    hook_catalog,
    require_stable_ids,
    todo_hook,
    write_hook_switch,
)
from harness_lib.add_todo_models import AddTodoRequest, Closing, ResearchLevel  # noqa: E402
from harness_lib.config import ConfigError, HarnessConfig, activate, load_config  # noqa: E402
from harness_lib.project import project_root  # noqa: E402

WHO = "add-todo"
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


def _ready(cfg: HarnessConfig) -> None:
    """Refuse a project the agent could not add to: no TODO folder, no catalog yet, or rank-tied ids."""
    _refuse_legacy(catalog_file(cfg, WHO))


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
    if data is not None:
        require_stable_ids(data, WHO)


def _item(cfg: HarnessConfig, todo_id: str) -> Dict[str, Any]:
    """The catalog item with ``todo_id``, read through the gate ``add_note.py goal --todo`` shares.

    Refuses what ``hook_catalog`` refuses (an unreadable catalog included) and an id the catalog lacks.
    """
    item = catalog_item(hook_catalog(cfg, WHO, WHO), todo_id)
    if item is None:
        raise Refused(f"hook: no catalog item {todo_id}")
    return item


def _switch_path(cfg: HarnessConfig) -> Path:
    """The hook switch file under ``state_dir``."""
    return cfg.path(cfg.state_dir) / HOOK_REL


def _clear(cfg: HarnessConfig, args: argparse.Namespace) -> str:
    """Remove the switch, fired or not; needs no TODO catalog. Returns the line to print.

    Refuses ``--clear`` mixed with ``--todo`` or ``--closed-by``, as ``add_note.py goal --clear`` does.
    """
    if args.todo or args.closed_by:
        raise Refused("hook --clear takes no --todo or --closed-by")
    return "hook: cleared" if clear_switch(_switch_path(cfg)) else "hook: none"


def _hook(cfg: HarnessConfig, args: argparse.Namespace) -> str:
    """Arm the switch for a catalog item; returns the line to print."""
    if not args.todo or not args.closed_by:
        raise Refused("hook needs --todo <id> and --closed-by, or --clear")
    hook = todo_hook(Closing(args.closed_by), _item(cfg, args.todo))
    write_hook_switch(_switch_path(cfg), hook, arming_session(os.environ))
    return f"hook: armed {hook.todo_id} ({hook.closed_by.value}); goal: {hook.goal()}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
    args = _parser().parse_args(argv)
    try:
        cfg = activate(load_config(project_root(args.repo)))
        if args.command == "hook" and args.clear:
            print(_clear(cfg, args))
            return 0
        _ready(cfg)
        if args.command == "hook":
            print(_hook(cfg, args))
            return 0
    except (ConfigError, Refused, OSError, ValueError) as exc:
        print(f"problem: {' '.join(str(exc).split())}", file=sys.stderr)
        return 1
    hook = None if args.hook is None else Closing(args.hook)
    request = AddTodoRequest(issue=args.issue, research=ResearchLevel(args.research), hook=hook)
    print("\n".join(dispatch_row(request, cfg.project_root)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
