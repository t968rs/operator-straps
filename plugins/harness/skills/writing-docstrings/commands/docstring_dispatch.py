"""Print the ``harness:docstring-writer`` dispatch rows for the files and symbols of a docstring request.

Usage: docstring_dispatch.py [--repo DIR] [--include-new | -in] [--parallel | -p] <path> [<path> ...]
       [<symbol> ...]
       docstring_dispatch.py [--repo DIR] --clear-probe

A path is a ``.py`` file, ``file.py::name`` (that file narrowed to ``name``) or a folder (its git-tracked
``.py`` files); a bare symbol narrows the one file in scope. Flags may sit between paths. Each row is a header
line ``agent=harness:docstring-writer model=<m>`` and its prompt lines; rows are separated by one blank line.
With ``--parallel`` and two or more files, one probe file is written per target folder and the probe row
prints first. Every run first removes the probes an earlier run recorded under ``state_dir``;
``--clear-probe`` does only that and prints ``cleared <path>`` per probe.

The project is ``--repo`` when given, else the checkout of the first path. Every defect is one ``problem:``
line on stderr with exit 1, nothing on stdout and no probe written.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, NoReturn, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from harness_lib.config import ConfigError, activate, load_config  # noqa: E402
from harness_lib.project import project_root  # noqa: E402
from harness_lib.writing_docstrings_api import (  # noqa: E402
    DispatchError,
    clear_probes,
    first_path,
    plan_rows,
    probe_row,
    resolve_scope,
    write_probes,
)
from harness_lib.writing_docstrings_models import PROBE_RECORD  # noqa: E402


class _Parser(argparse.ArgumentParser):
    """An argument parser whose errors raise ``DispatchError`` instead of exiting 2."""

    def error(self, message: str) -> NoReturn:
        raise DispatchError([message])


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="docstring_dispatch.py", description=__doc__.splitlines()[0], allow_abbrev=False)
    parser.add_argument("--repo", help="A directory inside the project (default: the first path's checkout).")
    parser.add_argument("--include-new", "-in", dest="include_new", action="store_true",
                        help="Write docstrings for undocumented functions in scope.")
    parser.add_argument("--parallel", "-p", action="store_true", help="One row per file, after a tool probe.")
    parser.add_argument("--clear-probe", dest="clear_probe", action="store_true",
                        help="Remove the recorded probe files and exit.")
    parser.add_argument("tokens", nargs="*", help="Paths, file.py::name tokens and bare symbols.")
    return parser


def _start(args: argparse.Namespace, cwd: Path) -> Path:
    """The folder the project is found from: ``--repo``, else the first path's nearest existing folder."""
    if args.repo:
        return Path(args.repo).resolve()
    path = first_path(args.tokens, cwd)
    if path is None:
        return cwd
    while not path.is_dir() and path != path.parent:
        path = path.parent
    return path


def _output(args: argparse.Namespace, cwd: Path) -> List[str]:
    """The stdout blocks; raises ``DispatchError`` or ``ConfigError``."""
    cfg = activate(load_config(project_root(_start(args, cwd))))
    root = cfg.project_root.resolve()
    record = cfg.path(cfg.state_dir) / PROBE_RECORD
    cleared = clear_probes(root, record)
    if args.clear_probe:
        return [f"cleared {path.as_posix()}" for path in cleared]
    if not args.tokens:
        raise DispatchError(["no path given; name a .py file, file.py::name or a folder"])
    scopes = resolve_scope(root, args.tokens, cwd)
    rows = plan_rows(root, scopes, new_docstrings=args.include_new, parallel=args.parallel)
    if len(rows) < 2:
        return [row.text() for row in rows]
    probe = probe_row(root, write_probes(root, scopes, record))
    return [probe.text(), *(row.text() for row in rows)]


def main(argv: Optional[List[str]] = None) -> int:
    cwd = Path.cwd()
    try:
        args = _parser().parse_intermixed_args(argv)
        blocks = _output(args, cwd)
    except (DispatchError, ConfigError) as exc:
        problems = exc.problems if isinstance(exc, DispatchError) else [str(exc)]
        print("\n".join(f"problem: {problem}" for problem in problems), file=sys.stderr)
        return 1
    if blocks:
        print(("\n" if args.clear_probe else "\n\n").join(blocks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
