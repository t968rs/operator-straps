#!/usr/bin/env python3
"""add-todo driver: print the ``harness:todo-editor`` dispatch row for one note.

``row [--issue] [-r|--research 0-3]``
    Print the ``agent=`` line (the model the research level picks) and the prompt header: ``SKILL``,
    ``Operation: add``, ``Issue``, ``Research`` and ``Project root``. The session appends ``Note:`` and
    ``Context:``; the note never reaches this command. Refuses, with one ``problem:`` line on stderr and exit
    1, a project without ``todo.folder`` and one whose catalog does not exist yet (``todo_sync.py init``
    creates it). A research level outside 0-3 is an argument error, exit 2.

``--repo`` (default: the working directory) names a directory inside the project.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib.add_todo_api import dispatch_row  # noqa: E402
from harness_lib.add_todo_models import AddTodoRequest, ResearchLevel  # noqa: E402
from harness_lib.config import ConfigError, HarnessConfig, activate, load_config  # noqa: E402
from harness_lib.project import project_root  # noqa: E402

INIT = "todo_sync.py init"


class Refused(Exception):
    """A refused row; the message is the ``problem:`` text."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print the harness:todo-editor dispatch row for add-todo.")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Directory inside the project.")
    sub = parser.add_subparsers(dest="command", required=True)
    row = sub.add_parser("row", help="Print the dispatch row.")
    row.add_argument("--issue", action="store_true", help="File a GitHub issue for the item.")
    row.add_argument("-r", "--research", type=int, choices=[int(level) for level in ResearchLevel],
                     default=int(ResearchLevel.NONE), help="Research level: 0 (none) to 3 (exhaustive).")
    return parser


def _ready(cfg: HarnessConfig) -> None:
    """Refuse a project the agent could not add to: no TODO folder, or no catalog yet."""
    if not cfg.todo.enabled or cfg.todo.catalog is None:
        raise Refused("add-todo needs todo.folder in .claude/harness.json")
    catalog = cfg.path(cfg.todo.catalog)
    if not catalog.is_file():
        raise Refused(f"no TODO catalog at {cfg.todo.catalog}; create it with {INIT}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
    args = _parser().parse_args(argv)
    try:
        cfg = activate(load_config(project_root(args.repo)))
        _ready(cfg)
    except (ConfigError, Refused, OSError) as exc:
        print(f"problem: {' '.join(str(exc).split())}", file=sys.stderr)
        return 1
    request = AddTodoRequest(issue=args.issue, research=ResearchLevel(args.research))
    print("\n".join(dispatch_row(request, cfg.project_root)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
