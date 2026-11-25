"""Suggest a docstring tier (1 brief, 2 compact, 3 full) per function in a Python file and flag format issues.

Usage: docstring_tiers.py [--repo DIR] <file.py> [<symbol> ...]

Prints one line per function or method (only the named symbols when any are given; a symbol matches a qualname
or its last part)::

    <line> <qualname> lines=<n> forks=<n> suggest=<tier> current=<layout> [flags]

The line limit is the project's ``docstrings.line_length``. The project is ``--repo`` when given, else the one
holding the file. A named symbol that matches no function, a missing file, source that does not parse or
decode as UTF-8 and an invalid configuration are each one ``problem:`` line on stderr with exit 1. Nothing is
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
from harness_lib.writing_docstrings_api import report, unmatched  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docstring_tiers.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="A directory inside the project (default: the file's project).")
    parser.add_argument("file", help="The Python file to measure.")
    parser.add_argument("symbols", nargs="*", help="Function or method names, or qualnames, to report.")
    return parser


def _rows(args: argparse.Namespace) -> List[str]:
    """The report lines; raises ``OSError``, ``SyntaxError``, ``ValueError`` (``ConfigError``,
    ``UnicodeDecodeError`` and null-byte source included) or ``LookupError``."""
    path = Path(args.file).resolve()
    if not path.is_file():
        raise OSError(f"{args.file}: no such file")
    start = Path(args.repo).resolve() if args.repo else path.parent
    cfg = activate(load_config(project_root(start)))
    rows = report(path, args.symbols, cfg.docstrings.line_length)
    missing = unmatched(rows, args.symbols)
    if missing:
        raise LookupError(f"no function named {', '.join(missing)} in {args.file}")
    return [row.row() for row in rows]


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        lines = _rows(args)
    except SyntaxError as exc:
        print(f"problem: {args.file}:{exc.lineno}: {exc.msg}", file=sys.stderr)
        return 1
    except (OSError, ConfigError, LookupError) as exc:
        print(f"problem: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"problem: {args.file}: {exc}", file=sys.stderr)
        return 1
    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
