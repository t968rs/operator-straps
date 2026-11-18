"""Keep the per-branch override of the working refs the working-refs mod shows.

Usage: working.py [--repo PATH] set TOKENS... | clear | list

The override file is ``<state_dir>/working-refs/overrides.json`` under the project root, one entry per branch
(a detached HEAD is keyed ``(detached)``); ``harness_lib.working_refs`` owns its shape. ``set`` stores the
TODO ids and issues the tokens name for the current branch, filling the issues from the TODO catalog when the
tokens name none.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

GIT_TIMEOUT = 30


def context(repo: Path) -> Tuple[Path, Dict[str, Any]]:
    """The override file and the TODO catalog data (empty when none is configured or readable)."""
    from harness_lib.config import activate, load_config
    from harness_lib.project import project_root
    from harness_lib.todo_sync.sources import read_json
    from harness_lib.working_refs import OVERRIDES_REL
    root = project_root(repo)
    cfg = activate(load_config(root))
    found = read_json(cfg.project_root, cfg.todo.catalog) if cfg.todo.catalog else None
    catalog = found.data if found is not None and found.ok else {}
    return cfg.path(cfg.state_dir) / OVERRIDES_REL, catalog


def current_branch(repo: Path) -> str:
    """The checked-out branch name, or ``DETACHED`` when HEAD names none."""
    from harness_lib.working_refs import DETACHED, WorkingRefsError
    try:
        done = subprocess.run(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=GIT_TIMEOUT, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkingRefsError(f"cannot read the current branch of {repo}") from exc
    name = done.stdout.strip()
    return DETACHED if name in ("", "HEAD") else name


def do_set(repo: Path, tokens: list) -> str:
    from harness_lib.working_refs import fill_issues, format_refs, parse_refs, set_override
    path, catalog = context(repo)
    refs = fill_issues(parse_refs(tokens), catalog)
    branch = current_branch(repo)
    set_override(path, branch, refs)
    return f"{branch}: {format_refs(refs)}"


def do_clear(repo: Path) -> str:
    from harness_lib.working_refs import clear_override
    path, _catalog = context(repo)
    branch = current_branch(repo)
    return f"cleared {branch}" if clear_override(path, branch) else f"no override for {branch}"


def do_list(repo: Path) -> str:
    from harness_lib.working_refs import format_refs, read_overrides
    path, _catalog = context(repo)
    lines = [f"{branch}: {format_refs(refs)}" for branch, refs in read_overrides(path).items()]
    return "\n".join(lines) or "no overrides"


def parse_args(argv: Optional[list]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="project to write under (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("set", help="store the refs for the current branch").add_argument("tokens", nargs="+")
    sub.add_parser("clear", help="drop the current branch's override")
    sub.add_parser("list", help="print every branch's override")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> str:
    if args.command == "set":
        return do_set(args.repo, args.tokens)
    return do_list(args.repo) if args.command == "list" else do_clear(args.repo)


def main(argv: Optional[list] = None) -> int:
    from harness_lib.config import ConfigError
    try:
        print(run(parse_args(argv)))
    except (ValueError, ConfigError, OSError) as exc:
        print(f"working: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
