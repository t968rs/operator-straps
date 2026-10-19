"""todo_sync driver: check a project's TODO, research and plan artifacts for drift, render the snapshot,
write the runner pointer.

``check [--format summary|json|markdown] [--out PATH] [--rules S1,S2] [--fail-on error|warn]``
    Run the rule catalog and write the report (``TodoSyncReport.schema.json``) atomically to ``--out`` or
    ``<state_dir>/todo-sync/report.json``. ``summary`` prints one ``todo-sync drift=...`` line, ``json``
    the report, ``markdown`` a findings table. Exit 0, or 1 when a finding reaches the ``--fail-on``
    severity (``error``: any error; ``warn``: any warn or error). With ``todo.catalog`` null the check is
    inactive: one line, exit 0, nothing written.
``render [--date YYYY-MM-DD]``
    Write ``<todo.snapshots.dir>/TODO_Snapshot_<YYYY>_<MMDD>.md`` (header line, title, top-N table) and
    print its path.
``runner``
    Write ``<state_dir>/todo-sync/runner.json`` (interpreter, this script, project, report) and print its
    path.

``--project`` (default: the git top level of the working directory) and ``--config`` (an alternate
``harness.json``) go before or after the subcommand. A configuration error, an unknown rule id or a
refused render exits 2 with one ``problem:`` line on stderr.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib.config import ConfigError, HarnessConfig, activate, load_config  # noqa: E402
from harness_lib.project import project_root  # noqa: E402
from harness_lib.todo_sync import (TodoSyncError, check, render_snapshot, report_path,  # noqa: E402
                                   write_report, write_runner)
from harness_lib.todo_sync.report import Report, format_markdown, format_summary  # noqa: E402

INACTIVE = "todo sync inactive (todo.catalog is null)"
#: ``--fail-on`` thresholds, lowest severity first.
FAIL_LEVELS = ("warn", "error")


def _globals() -> argparse.ArgumentParser:
    """``--project`` / ``--config``, accepted before or after the subcommand."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", type=Path, default=argparse.SUPPRESS,
                        help="Project root (default: the git top level of the working directory).")
    common.add_argument("--config", type=Path, default=argparse.SUPPRESS,
                        help="Alternate harness.json read instead of <project>/.claude/harness.json.")
    return common


def _parser() -> argparse.ArgumentParser:
    common = _globals()
    parser = argparse.ArgumentParser(prog="todo_sync.py", description=__doc__.splitlines()[0],
                                     parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)
    chk = sub.add_parser("check", parents=[common], help="Run the sync rules and write the report.")
    chk.add_argument("--format", choices=("summary", "json", "markdown"), default="summary")
    chk.add_argument("--out", type=Path, help="Report path (default: <state_dir>/todo-sync/report.json).")
    chk.add_argument("--rules", help="Comma-separated rule ids to run (default: all).")
    chk.add_argument("--fail-on", choices=FAIL_LEVELS,
                     help="Exit 1 when a finding reaches this severity (warn: any warn or error).")
    rnd = sub.add_parser("render", parents=[common], help="Write the dated top-N snapshot.")
    rnd.add_argument("--date", type=dt.date.fromisoformat, help="Snapshot date (default: today).")
    sub.add_parser("runner", parents=[common], help="Write the runner pointer.")
    return parser


def _config(args: argparse.Namespace) -> HarnessConfig:
    start = getattr(args, "project", None)
    root = project_root(Path(start)) if start is not None else project_root()
    return activate(load_config(root, getattr(args, "config", None)))


def _emit(report: Report, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    elif fmt == "markdown":
        print(format_markdown(report), end="")
    else:
        print(format_summary(report))


def _check(cfg: HarnessConfig, args: argparse.Namespace) -> int:
    if not cfg.todo.enabled:
        print(INACTIVE)
        return 0
    rules = args.rules.split(",") if args.rules else None
    report = check(cfg, rules)
    write_report(report, args.out or report_path(cfg))
    _emit(report, args.format)
    return 1 if args.fail_on and _fails(report, args.fail_on) else 0


def _fails(report: Report, level: str) -> bool:
    """True when a finding reaches ``level``: ``error`` counts errors, ``warn`` counts warns and errors."""
    reached = FAIL_LEVELS[FAIL_LEVELS.index(level):]
    return any(report.by_severity(severity) for severity in reached)


def _dispatch(cfg: HarnessConfig, args: argparse.Namespace) -> int:
    if args.command == "check":
        return _check(cfg, args)
    if args.command == "render":
        print(render_snapshot(cfg, args.date or dt.date.today()))
    else:
        print(write_runner(cfg))
    return 0


def _utf8_streams() -> None:
    """Reconfigure stdout and stderr to UTF-8 where the stream supports it."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
    _utf8_streams()
    args = _parser().parse_args(argv)
    try:
        return _dispatch(_config(args), args)
    except (ConfigError, TodoSyncError, OSError) as exc:
        message = " ".join(str(exc).split())
        print(f"problem: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
