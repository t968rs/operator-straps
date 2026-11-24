"""Print the section outline of Python files from their divider comments, with every flag the dividers raise.

Usage: comment_sections.py [--repo DIR] <file.py> [<file.py> ...]

Prints, per file in the order named, one line per divider and per flag, in line order::

    <path>:<line>: major|minor <title>
    <path>:<line>: flag width|style|banner: <comment text>

or ``<path>: no dividers``. Each path is relative to the project. The divider width is the project's
``comments.divider_width``; the project is ``--repo`` when given, else the one holding the first file. No
path, a missing file, a file that is not ``.py``, source that does not tokenize or decode as UTF-8 and an
invalid configuration are each one ``problem:`` line on stderr with exit 1 and nothing on stdout. Nothing is
written.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from harness_lib.config import ConfigError, activate, load_config  # noqa: E402
from harness_lib.project import project_root  # noqa: E402
from harness_lib.writing_comments_api import report_lines, sections  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comment_sections.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="A directory inside the project (default: the first file's project).")
    parser.add_argument("files", nargs="*", help="The Python files to outline.")
    return parser


def _resolve(files: List[str]) -> List[Path]:
    """Each named file, resolved; raises ``ValueError`` naming every path that is missing or not ``.py``."""
    if not files:
        raise ValueError("no file named; pass one or more .py files")
    problems = []
    for name in files:
        path = Path(name).resolve()
        if not path.is_file():
            problems.append(f"{name}: no such file")
        elif path.suffix != ".py":
            problems.append(f"{name}: not a .py file")
    if problems:
        raise ValueError("; ".join(problems))
    return [Path(name).resolve() for name in files]


def _label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _lines(args: argparse.Namespace) -> List[str]:
    """The report lines of every file; raises ``ValueError`` (``ConfigError`` and decode errors included)."""
    paths = _resolve(args.files)
    root = project_root(Path(args.repo).resolve() if args.repo else paths[0].parent)
    width = activate(load_config(root)).comments.divider_width
    lines: List[str] = []
    for path in paths:
        label = _label(path, root.resolve())
        try:
            report = sections(path.read_text(encoding="utf-8"), width)
        except ValueError as exc:
            raise ValueError(f"{label}: {exc}") from exc
        lines += report_lines(label, report)
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        lines = _lines(args)
    except (ValueError, ConfigError, OSError) as exc:
        print(f"problem: {exc}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
