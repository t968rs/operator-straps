"""todo_sync driver: check a project's TODO, research and plan artifacts for drift, render the snapshot,
write the runner pointer, start a catalog, list untracked GitHub issues, add, retire, split or re-rank
catalog items, queue items in the inbox, hold the catalog lease, and switch a catalog to stable ids once.

``check [--format summary|json|markdown] [--out PATH] [--rules S1,S2] [--fail-on error|warn]``
    Run the rule catalog and write the report (``TodoSyncReport.schema.json``) atomically to ``--out`` or
    ``<state_dir>/todo-sync/report.json``. ``summary`` prints one ``todo-sync drift=...`` line, ``json``
    the report, ``markdown`` a findings table. Exit 0, or 1 when a finding reaches the ``--fail-on``
    severity (``error``: any error; ``warn``: any warn or error). With ``todo.folder`` null the check is
    inactive: one line, exit 0, nothing written. A ``--rules`` run marks each left-out rule ``not selected``
    in ``rules_skipped``; the todo-watch mod ignores such a subset report instead of reading its drift as
    the whole project's.
``render [--date YYYY-MM-DD]``
    Write ``<todo.snapshots.dir>/TODO_Snapshot_<YYYY>_<MMDD>.md`` (header line, title, top-N table) and
    print its path.
``runner``
    Write ``<state_dir>/todo-sync/runner.json`` (interpreter, this script, project, report) and print its
    path.
``retire ID [ID ...] [--dry-run] [--lease TOKEN]``
    Remove finished items (``todo-k7qf`` or ``k7qf``, any case) from the catalog and record their ids in
    ``retired_ids``, which no new id reuses. Ids are stable, so nothing is renumbered and no id is
    rewritten: the kept items take ranks 1..n in order, items that lose their only unblocked item are
    rescored, the counts recomputed, and only the catalog is written. Prints the follow-up the catalog
    cannot record by itself: resolved issues to list as close candidates, trackers to revisit, research
    catalog and stub lines naming a retired id (``dangling:``), and other files naming a retired id
    (``reference (not rewritten):``; the snapshots and the history folders, ``artifacts.plans``,
    ``reviews``, ``commit_messages``, ``summaries``, ``scratch`` and each planning prefix, are skipped, and so
    are the TODO inbox (``<scratch_folder>/todo-inbox``) and ``state_dir``).
    ``--dry-run`` prints the same report and writes nothing.
``split ID --spec PATH [--dry-run] [--lease TOKEN]``
    Replace one item with the parts in the spec file (``{"parts": [{...}, {...}]}``, each a set of field
    overrides laid over a copy of the item; ``title`` required, ``id`` / ``rank`` / ``priority`` refused).
    Every part gets a new id drawn past every live and retired id; the original id joins ``retired_ids``
    and ``split_ids`` records its parts in spec order. Parts inherit the item's links, tracker and close
    candidates; then rescore, re-rank and recount. No id is rewritten: research catalog and stub lines
    naming the split id are listed as ``dangling:`` with its parts, and other files naming it as
    ``reference (not rewritten):``, for a person to point at the right part. A dry run draws its own ids;
    the real run draws again.
``refresh [--dry-run] [--lease TOKEN]``
    Rescore every item from ``ranking_method``, re-sort and set each rank to its position, after hand edits
    to item fields. Ids never change and only the catalog is written. A catalog already in order is left
    untouched.
``init [--lease TOKEN]``
    Create the TODO folder, an empty schema-valid catalog (the default ranking tables, no items, the current
    commit in ``generated_from``) and the first snapshot (skipped when ``todo.snapshots.dir`` is null). Prints
    one ``created <path>`` line per file. Refuses, exit 2 and nothing written, when the catalog already exists
    or the snapshot name does not match ``todo.snapshots.name_pattern``; needs ``todo.folder`` and a git
    commit. A snapshot that fails after the catalog is written names the catalog and ``render`` as the way on.
``untracked``
    List the open GitHub issues (``gh issue list``; ``todo.gh.repo``, else the repository ``gh`` resolves for
    the checkout) that no catalog record covers: no item that resolves it (``gh_issues`` or a ``gh_issue``
    source; ``related_gh_issues`` does not count), tracker, child, close candidate or research entry. Prints
    one ``#N title`` line
    per issue and writes the rows (issue text, comments and the text of linked PR reviews) to
    ``<state_dir>/todo-sync/untracked.json``. Prints ``untracked: none`` and writes nothing when every open
    issue is recorded. Refuses, exit 2, when ``gh`` fails, returns no JSON list, or the listing reaches the
    issue limit (the result may be cut off), or the catalog still holds ``TODO-NNN`` ids (naming
    ``migrate-ids``).
``add (--spec PATH | --inbox) [--dry-run] [--file-issue] [--lease TOKEN]``
    Add one item per entry of the spec file (``{"items": [{...}, {...}]}``; each holds the fields a person
    judges, never ``id``, ``rank`` or ``priority``, and names its ``issue`` and ``url`` or neither). The
    script draws each item a new stable id past every live and retired id, builds the source
    (``gh_issue``, or for an entry with neither a local-only ``note`` dated today), scores the item,
    re-sorts and recounts; no other id changes and only the catalog is written. A dry run draws its own
    ids; the real run draws again. An issue the catalog already records is refused. ``--file-issue`` files
    a GitHub issue (``gh issue create``, in ``todo.gh.repo`` when set) for each entry that names none, after
    the whole spec passes a dry run, and records it as the ``gh_issue`` source; a failure after filing
    names the issues filed. A dry run files nothing, labels each such item ``(issue to file)`` and prints
    ``would file N issue(s)``. ``--inbox`` replaces ``--spec`` (one of the two is required): every queued
    inbox file is added in one catalog write, oldest first; accepted files are deleted, a refused one is
    renamed ``<name>.rejected.json`` beside a ``<name>.reason.txt``; when any item landed, the snapshot is
    rendered and the check run. Prints one
    ``inbox: added N item(s): <id> (#N|note), ...[; rejected K (<files>)]; check drift=D`` line when an item
    landed, ``inbox: rejected K (<files>)`` when every queued file was refused, or ``inbox: empty`` without
    taking the lock when no file is queued. ``--inbox`` refuses ``--dry-run`` and ``--file-issue``
    (``inbox put`` files issues).
``inbox put --spec PATH [--file-issue]``
    Queue the items of an ``add`` spec in the inbox (``<scratch_folder>/todo-inbox/``), one file per item,
    after a dry run of the whole spec against the catalog; the catalog is never written and no lock is
    taken. ``--file-issue`` files an issue for each entry that names none first, as ``add`` does. Prints one
    ``queued <repo-relative path>`` line per file and one ``filed #N <url>`` line per issue filed.
``lease acquire --owner TEXT``
    Take the catalog lease for a run of several commands and print ``lease: <token>``. Until it is released
    every catalog write without ``--lease <token>`` (the todo-watch mod's drain included) waits, then refuses
    naming the holder. A lease turns stale after 30 minutes.
``lease release TOKEN``
    Recount the catalog (no rescore or rerank; written only when the counts change), render the snapshot
    (when ``todo.snapshots.dir`` is set), run the check, write its report and free the lease; prints
    ``lease released; counts updated|unchanged``, ``rendered <path>`` and ``check drift=D``. A wrong token
    or no lease refuses and frees nothing; a recount, render or check failure still frees the lease and
    exits 2.
``lease break``
    Remove whatever lock or lease the catalog holds, the manual override for a crashed holder. Prints the
    removed holder's owner, mode and age, or ``lease: none held``.
``migrate-ids [--dry-run] [--exclude PATH]... [--lease TOKEN]``
    Switch a catalog from rank-tied ``TODO-NNN`` ids to stable ``todo-xxxx`` ids, once. Each item draws an
    id seeded from its old id and title, so a dry run and its real run (and two checkouts of one catalog)
    agree; the ``old -> new`` map is stored in the catalog's ``legacy_ids``. Every live file naming an old
    id is rewritten through the map: the research catalog, the stubs and each tracked or untracked text
    file ``git grep`` finds, source and tests included, minus the catalog schema, the history folders
    ``retire`` skips and each ``--exclude`` (repeatable; absolute or relative to the working directory, and
    refused unless it lies below the project root; matched by path component: ``vendor`` skips
    ``vendor/x.md``, never ``vendored.md``). The project's
    ``todo.catalog_schema``, when set, must accept the migrated catalog: a real run refuses before any
    write, a dry run reports it as ``schema:``. A rerun on a migrated catalog rewrites the remaining live
    references through the stored map and adds new legacy ids to it; a legacy id the map already holds is
    refused. ``--dry-run`` prints the new ids and the files it would rewrite and writes nothing. A real run
    holds the catalog lease for its whole run (its ``git grep`` and rewrites can outlast a write lock) and
    frees it afterwards, without the ``lease release`` recount; with ``--lease TOKEN`` it runs under that
    held lease instead and leaves it held.

Every catalog write (``init``, ``add``, ``retire``, ``split``, ``refresh``; not a dry run) holds the catalog
lock, ``<state_dir>/locks/<catalog path with '/' as '__'>.lock``: the write lock for one command, or with
``--lease TOKEN`` the lease that token names (a wrong token refuses at once). A lock another owner holds is
waited on for 10 seconds, then refused naming its owner, mode and age. ``check``, ``render``, ``runner``,
``untracked``, ``inbox put`` and every dry run take no lock.

``--project`` (default: the git top level of the working directory) and ``--config`` (an alternate
``harness.json``) go before or after the subcommand. A configuration error, an unknown rule id or any
refused operation (render, init, add, retire, split, refresh, migrate-ids, inbox put, lease, a lock held by
another owner, a failed ``gh`` call) exits 2 with one ``problem:`` line on stderr. A catalog still holding
``TODO-NNN`` ids refuses untracked, add, retire, split and refresh, naming ``migrate-ids``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
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
from harness_lib.todo_sync.migrate import apply_migration, exclude_paths  # noqa: E402
from harness_lib.todo_sync.migrate import summary_lines as migrate_lines  # noqa: E402
from harness_lib.todo_sync.report import Report, format_markdown, format_summary  # noqa: E402
from harness_lib.todo_sync.reshape import apply_add, apply_refresh, apply_split  # noqa: E402
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
GUARDED = ("init", "add", "retire", "split", "refresh")


def _summary() -> str:
    """The module docstring's first paragraph on one line, used as the argparse description."""
    return " ".join((__doc__ or "").split("\n\n")[0].split())


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
    rnd = sub.add_parser("render", parents=[common], help="Write the dated top-N snapshot.")
    rnd.add_argument("--date", type=dt.date.fromisoformat, help="Snapshot date (default: today).")
    sub.add_parser("runner", parents=[common], help="Write the runner pointer.")
    _reshapers(sub, common)
    ini = sub.add_parser("init", parents=[common],
                         help="Create the TODO folder, an empty catalog and a snapshot.")
    ini.add_argument("--lease", metavar="TOKEN", help=LEASE_HELP)
    sub.add_parser("untracked", parents=[common], help="List open issues no catalog record mentions.")
    _adders(sub, common)
    _leases(sub, common)
    _migrator(sub, common)
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


def _leases(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """``lease acquire``, ``lease release`` and ``lease break``."""
    lease = sub.add_parser("lease", parents=[common], help="Hold the catalog lock across several commands.")
    lease_sub = lease.add_subparsers(dest="lease_command", required=True)
    acq = lease_sub.add_parser("acquire", parents=[common], help="Take the lease and print its token.")
    acq.add_argument("--owner", required=True, help="Who holds the lease, named in every refusal.")
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
    """``inbox put``: queue the spec's items and name each file and filed issue."""
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
        print(f"lease: {locking.acquire(cfg, args.owner)}")
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


def _write(cfg: HarnessConfig, args: argparse.Namespace) -> int:
    """The catalog writes ``init``, ``add --spec``, ``retire``, ``split`` and ``refresh``, or a dry run."""
    dry = getattr(args, "dry_run", False)
    if args.command == "init":
        return _init(cfg)
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
