#!/usr/bin/env python3
"""spec-it driver: check a written spec sheet and name the plan step that takes it.

``check <path> [--refs REF ...]``
    Parse the sheet at ``<path>`` (relative to the project root, or absolute) and print
    ``check [ok] | <path> | <n> lines | <g> goals | <a> avoid``, a ``warn:`` line when the page runs past the
    250-line target, and ``next: /harness:write-plan "<title>" --spec "<path>"``. Each ``--refs`` value (a
    TODO id or an issue number, comma-joined values split, repeats dropped) follows on the ``next:`` line as a
    single-quoted ``--refs`` token. A missing sheet, a page out of the layout ``render_sheet`` writes, a page
    over 500 lines, a banned field (an id, an issue number, a URL, a code fence) and a ref that is neither a
    TODO id nor an issue number are refused: one ``problem:`` line each on stderr, exit 1.

``--repo`` (default: the working directory) names a directory inside the project.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from pydantic import ValidationError  # noqa: E402

from harness_lib.config import ConfigError, activate, active, load_config  # noqa: E402
from harness_lib.project import project_root  # noqa: E402
from harness_lib.spec_it_api import TARGET_LINES, load_sheet, next_step, plan_refs  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check a spec sheet written by the spec-it skill.")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Directory inside the project.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="Validate a sheet and print the write-plan step.")
    check.add_argument("path", help="The sheet, relative to the project root or absolute.")
    check.add_argument("--refs", nargs="+", default=[], metavar="REF",
                       help="TODO ids and issue numbers the work answers, carried to the next: line.")
    return parser


def _problems(exc: Exception) -> List[str]:
    """One message per defect: each validation error, else the exception's own text."""
    if isinstance(exc, ValidationError):
        return [error["msg"].removeprefix("Value error, ") for error in exc.errors()]
    return [str(exc)]


def check(rel: str, refs: Sequence[str] = ()) -> List[str]:
    """The report lines for the sheet at ``rel``, ``refs`` on its ``next:`` line; raises ``ValueError`` or
    ``OSError`` on a refusal."""
    plan_refs(refs)
    path = Path(rel) if Path(rel).is_absolute() else active().path(rel)
    if not path.is_file():
        raise FileNotFoundError(f"no spec sheet at {rel}")
    sheet = load_sheet(path)
    count = len(path.read_text(encoding="utf-8").splitlines())
    lines = [f"check [ok] | {Path(rel).as_posix()} | {count} lines | {len(sheet.goals)} goals | "
             f"{len(sheet.avoid)} avoid"]
    if count > TARGET_LINES:
        lines.append(f"warn: {count} lines, past the {TARGET_LINES}-line target; tighten the goals")
    lines.append(f"next: {next_step(sheet, path, refs)}")
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        activate(load_config(project_root(args.repo)))
        print("\n".join(check(args.path, args.refs)))
    except (ConfigError, OSError, ValueError) as exc:
        for problem in _problems(exc):
            print(f"problem: {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
