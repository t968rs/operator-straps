"""todo_sync driver: check a project's TODO, research and plan artifacts for drift, render the snapshot,
write the runner pointer, start a catalog, list untracked GitHub issues, add, retire, split or re-rank
catalog items, queue items and field updates in the inbox, hold the catalog lease, and switch a catalog to
stable ids once.

Every command, option and exit code, the catalog lock and which skill, agent, mod or person runs each
command are documented in ``todo_sync.md`` beside this script; a test checks that document against
the parser.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib.config import ConfigError, HarnessConfig, activate, load_config  # noqa: E402
from harness_lib.project import project_root  # noqa: E402
from harness_lib.todo_sync import (TodoSyncError, check, render_snapshot, report_path,  # noqa: E402
                                   write_report, write_runner)
from harness_lib.todo_sync import inbox, locking  # noqa: E402
from harness_lib.todo_sync.issues import find_untracked, write_untracked  # noqa: E402
from harness_lib.todo_sync.keywords import apply_keywords, guess_keyword, keyword_lines  # noqa: E402
from harness_lib.todo_sync.migrate import apply_migration, exclude_paths  # noqa: E402
from harness_lib.todo_sync.migrate import summary_lines as migrate_lines  # noqa: E402
from harness_lib.todo_sync.report import Report, format_markdown, format_summary  # noqa: E402
from harness_lib.todo_sync.reshape import apply_add, apply_refresh, apply_split, read_spec  # noqa: E402
from harness_lib.todo_sync.scaffold import init_catalog  # noqa: E402
from harness_lib.todo_sync.sources import posix  # noqa: E402
from harness_lib.todo_sync.reshape import summary_lines as reshape_lines  # noqa: E402
from harness_lib.todo_sync.retire import apply_retirement, summary_lines  # noqa: E402

INACTIVE = "todo sync inactive (todo.folder is null)"
#: ``--fail-on`` thresholds, lowest severity first.
FAIL_LEVELS = ("warn", "error")
#: Help for the item ids ``retire`` and ``split`` take.
ID_HELP = "Item ids: todo-k7qf or k7qf (any case)."
DRY_RUN_HELP = "Print the report; write nothing."
LEASE_HELP = "Run under the catalog lease this token names instead of taking the write lock."
#: The subcommands whose real run writes the catalog under ``locking.guard``.
GUARDED = ("init", "add", "retire", "split", "refresh", "keywords")


def _summary() -> str:
    """The module docstring's first paragraph on one line, used as the argparse description."""
    return " ".join((__doc__ or "").split("\n\n")[0].split())


def _seconds(text: str) -> float:
    """Argparse type of ``--wait``: a finite number of seconds, 0 or more."""
    try:
        value = float(text)
    except ValueError:
        value = -1.0
    if not (math.isfinite(value) and value >= 0):
        raise argparse.ArgumentTypeError("must be a number of seconds, 0 or more")
    return value


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
    parser = argparse.ArgumentParser(prog="todo_sync.py", description=_summary(),
                                     parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)
    chk = sub.add_parser("check", parents=[common], help="Run the sync rules and write the report.")
    chk.add_argument("--format", choices=("summary", "json", "markdown"), default="summary")
    chk.add_argument("--out", type=Path, help="Report path (default: <state_dir>/todo-sync/report.json).")
    chk.add_argument("--rules", help="Comma-separated rule ids to run (default: all).")
    chk.add_argument("--fail-on", choices=FAIL_LEVELS,
                     help="Exit 1 when a finding reaches this severity (warn: any warn or error).")
    rnd = sub.add_parser("render", parents=[common],
                         help="Bring the snapshot page and its stamp up to date (an unchanged page is kept).")
    rnd.add_argument("--date", type=dt.date.fromisoformat,
                     help="Render date of a rewritten page (default: today); a kept page keeps its own.")
    sub.add_parser("runner", parents=[common], help="Write the runner pointer.")
    _reshapers(sub, common)
    ini = sub.add_parser("init", parents=[common],
                         help="Create the TODO folder, an empty catalog and a snapshot.")
    ini.add_argument("--lease", metavar="TOKEN", help=LEASE_HELP)
    sub.add_parser("untracked", parents=[common], help="List open issues no catalog record mentions.")
    _adders(sub, common)
    _leases(sub, common)
    _migrator(sub, common)
    _keyworders(sub, common)
    return parser


def _adders(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """``add`` (from a spec or the inbox) and ``inbox put``."""
    add = sub.add_parser("add", parents=[common], help="Add one item per spec entry: issue or local note.")
    source = add.add_mutually_exclusive_group(required=True)
    source.add_argument("--spec", type=Path, help='JSON file: {"items": [{...}, {...}]}.')
    source.add_argument("--inbox", action="store_true", help="Add every item queued in the inbox.")
    add.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)
    add.add_argument("--file-issue", action="store_true",
                     help="File a GitHub issue for each item that names none, once the spec validates.")
    add.add_argument("--lease", metavar="TOKEN", help=LEASE_HELP)
    box = sub.add_parser("inbox", parents=[common], help="Queue drafted items without writing the catalog.")
    box_sub = box.add_subparsers(dest="inbox_command", required=True)
    put = box_sub.add_parser("put", parents=[common], help="Queue one inbox file per spec item.")
    put.add_argument("--spec", type=Path, required=True, help='JSON file: {"items": [{...}, {...}]}.')
    put.add_argument("--file-issue", action="store_true",
                     help="File a GitHub issue for each item that names none, once the spec validates.")
    put.add_argument("--update", action="store_true",
                     help='Queue field updates of existing items: the spec is {"updates": [{"id": ..., '
                          '"fields": {...}}]}.')


def _leases(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """``lease acquire``, ``lease release`` and ``lease break``."""
    lease = sub.add_parser("lease", parents=[common], help="Hold the catalog lock across several commands.")
    lease_sub = lease.add_subparsers(dest="lease_command", required=True)
    acq = lease_sub.add_parser("acquire", parents=[common], help="Take the lease and print its token.")
    acq.add_argument("--owner", required=True, help="Who holds the lease, named in every refusal.")
    acq.add_argument("--wait", type=_seconds, metavar="SECONDS",
                     help="Wait up to SECONDS for a held lease or write lock before refusing (default: 10).")
    rel = lease_sub.add_parser("release", parents=[common], help="Recount, check and free the lease.")
    rel.add_argument("token", help="The token lease acquire printed.")
    lease_sub.add_parser("break", parents=[common], help="Remove any lock or lease the catalog holds.")


def _reshapers(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """``retire``, ``split`` and ``refresh``: the structural edits of a stable-id catalog."""
    ret = sub.add_parser("retire", parents=[common],
                         help="Remove finished items and record their ids as retired.")
    ret.add_argument("ids", nargs="+", help=ID_HELP)
    spl = sub.add_parser("split", parents=[common], help="Replace one item with parts that get new ids.")
    spl.add_argument("id", help=ID_HELP)
    spl.add_argument("--spec", type=Path, required=True, help='JSON file: {"parts": [{...}, {...}]}.')
    ref = sub.add_parser("refresh", parents=[common], help="Rescore and re-rank every item.")
    for cmd in (ret, spl, ref):
        cmd.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)
        cmd.add_argument("--lease", metavar="TOKEN", help=LEASE_HELP)


def _migrator(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """``migrate-ids``: the one-time switch from ``TODO-NNN`` to stable ids."""
    mig = sub.add_parser("migrate-ids", parents=[common],
                         help="Give every item a stable id once and rewrite live references; a rerun "
                              "finishes through the stored map")
    mig.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)
    mig.add_argument("--exclude", action="append", default=[], metavar="PATH",
                     help="Leave files under PATH (absolute or relative to the working directory, below "
                          "the project root; matched by path component) as written; repeatable.")
    mig.add_argument("--lease", metavar="TOKEN",
                     help="Run under the catalog lease this token names instead of taking a lease of "
                          "its own.")


def _keyworders(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """``suggest-keyword`` (read-only guess per spec item) and ``keywords`` (the one-time catalog fill)."""
    sug = sub.add_parser("suggest-keyword", parents=[common],
                         help="Print the confident keyword guess of each spec item, or none.")
    sug.add_argument("--spec", type=Path, required=True, help='JSON file: {"items": [{...}, {...}]}.')
    kws = sub.add_parser("keywords", parents=[common],
                         help="Give every catalog item that lacks a keyword its confident guess.")
    kws.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)
    kws.add_argument("--lease", metavar="TOKEN", help=LEASE_HELP)


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


def _untracked(cfg: HarnessConfig) -> int:
    rows = find_untracked(cfg)
    if not rows:
        print("untracked: none")
        return 0
    print(f"untracked: {len(rows)} open issue(s) in no catalog record")
    print("\n".join(f"#{row['number']} {row['title']}" for row in rows))
    print(f"wrote {write_untracked(cfg, rows)}")
    return 0


def _init(cfg: HarnessConfig) -> int:
    result = init_catalog(cfg)
    for path in (result.catalog, result.snapshot):
        if path is not None:
            print(f"created {posix(str(path.relative_to(cfg.project_root)))}")
    print("next: todo_sync.py check, or /harness:sync-gh-todo to add the open issues")
    return 0


def _owner(args: argparse.Namespace) -> str:
    """The command a lock body names as its owner. Never an item id: the lock file lies inside the project,
    so an id in it would turn up in the reference scan of the very retire or split holding the lock."""
    return " ".join(["todo_sync.py", args.command, *(["--inbox"] if getattr(args, "inbox", False) else [])])


def _drain(cfg: HarnessConfig, args: argparse.Namespace) -> int:
    """``add --inbox``: ``inbox: empty`` without the lock when nothing is queued, else drain under it."""
    if args.dry_run or args.file_issue:
        raise TodoSyncError("add --inbox takes neither --dry-run nor --file-issue (inbox put files issues)")
    if not inbox.queued(cfg):
        print("inbox: empty")
        return 0
    with locking.guard(cfg, _owner(args), args.lease):
        print("\n".join(inbox.drain_lines(inbox.drain(cfg))))
    return 0


def _inbox(cfg: HarnessConfig, args: argparse.Namespace) -> int:
    """``inbox put``: queue the spec's items (or, with ``--update``, its field updates) and name each file
    and filed issue."""
    if args.update:
        if args.file_issue:
            raise TodoSyncError("inbox put --update takes no --file-issue (an update files no issue)")
        result = inbox.put_updates(cfg, args.spec)
    else:
        result = inbox.put(cfg, args.spec, args.file_issue)
    for path in result.paths:
        print(f"queued {posix(str(path.relative_to(cfg.project_root)))}")
    for number, url in result.filed:
        print(f"filed #{number} {url}")
    return 0


def _broken(body: Optional[dict]) -> str:
    """The ``lease break`` line for the removed lock body (None: nothing held, ``{}``: unreadable)."""
    if body is None:
        return "lease: none held"
    if not body:
        return "lease: broke an unreadable lock"
    acquired = body.get("acquired")
    known = isinstance(acquired, (int, float)) and not isinstance(acquired, bool)
    age = f"{time.time() - acquired:.0f}s old" if known else "age unknown"
    return f"lease: broke {body.get('owner')!r} ({body.get('mode')}, {age})"


def _lease(cfg: HarnessConfig, args: argparse.Namespace) -> int:
    """``lease acquire``, ``lease release`` and ``lease break``."""
    if args.lease_command == "acquire":
        print(f"lease: {locking.acquire(cfg, args.owner, args.wait)}")
    elif args.lease_command == "release":
        print("\n".join(locking.release(cfg, args.token)))
    else:
        print(_broken(locking.break_(cfg)))
    return 0


def _migrate(cfg: HarnessConfig, args: argparse.Namespace) -> int:
    """``migrate-ids``; a real run holds a lease of its own for the whole run, or the ``--lease`` one."""
    exclude = exclude_paths(cfg, args.exclude, Path.cwd())
    if args.dry_run:
        result = apply_migration(cfg, True, exclude)
    else:
        with locking.leased(cfg, _owner(args), args.lease):
            result = apply_migration(cfg, False, exclude)
    print("\n".join(migrate_lines(result, args.dry_run)))
    return 0


def _suggest(args: argparse.Namespace) -> int:
    """``suggest-keyword``: one ``item <n>: <guess|none>`` line per spec item, counted from 1."""
    for n, item in enumerate(read_spec(args.spec, "items"), 1):
        guess = guess_keyword(item) if isinstance(item, dict) else None
        print(f"item {n}: {guess or 'none'}")
    return 0


def _write(cfg: HarnessConfig, args: argparse.Namespace) -> int:
    """The catalog writes ``init``, ``add --spec``, ``retire``, ``split``, ``refresh`` and ``keywords``, or
    a dry run."""
    dry = getattr(args, "dry_run", False)
    if args.command == "init":
        return _init(cfg)
    if args.command == "keywords":
        print("\n".join(keyword_lines(apply_keywords(cfg, dry), dry)))
        return 0
    if args.command == "add":
        print("\n".join(reshape_lines(apply_add(cfg, args.spec, dry, file_issues=args.file_issue), dry)))
    elif args.command == "retire":
        print("\n".join(summary_lines(apply_retirement(cfg, args.ids, dry), dry)))
    elif args.command == "split":
        print("\n".join(reshape_lines(apply_split(cfg, args.id, args.spec, dry), dry)))
    else:
        print("\n".join(reshape_lines(apply_refresh(cfg, dry), dry)))
    return 0


def _unlocked(cfg: HarnessConfig, args: argparse.Namespace) -> int:
    """The subcommands that take no catalog lock of their own."""
    if args.command == "check":
        return _check(cfg, args)
    if args.command == "untracked":
        return _untracked(cfg)
    if args.command == "suggest-keyword":
        return _suggest(args)
    if args.command == "inbox":
        return _inbox(cfg, args)
    if args.command == "lease":
        return _lease(cfg, args)
    if args.command == "render":
        print(render_snapshot(cfg, args.date or dt.date.today()))
    else:
        print(write_runner(cfg))
    return 0


def _dispatch(cfg: HarnessConfig, args: argparse.Namespace) -> int:
    """Run the subcommand; every real catalog write runs inside ``locking.guard``."""
    if args.command == "add" and args.inbox:
        return _drain(cfg, args)
    if args.command == "migrate-ids":
        return _migrate(cfg, args)
    if args.command not in GUARDED:
        return _unlocked(cfg, args)
    if getattr(args, "dry_run", False):
        return _write(cfg, args)
    with locking.guard(cfg, _owner(args), getattr(args, "lease", None)):
        return _write(cfg, args)


def _utf8_streams() -> None:
    """Reconfigure stdout and stderr to UTF-8 where the stream supports it."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _problem_text(exc: BaseException) -> str:
    """Join the message and the notes, so a failed lease free is printed with the original error."""
    return " ".join(" ".join([str(exc), *getattr(exc, "__notes__", ())]).split())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
    _utf8_streams()
    args = _parser().parse_args(argv)
    try:
        return _dispatch(_config(args), args)
    except (ConfigError, TodoSyncError, OSError) as exc:
        message = _problem_text(exc)
        print(f"problem: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
