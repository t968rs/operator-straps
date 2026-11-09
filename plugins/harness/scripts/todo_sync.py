"""todo_sync driver: check a project's TODO, research and plan artifacts for drift, render the snapshot,
write the runner pointer, start a catalog, list untracked GitHub issues, add, retire, split or re-rank
catalog items, and switch a catalog to stable ids once.

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
``retire ID [ID ...] [--dry-run]``
    Remove finished items (``todo-k7qf`` or ``k7qf``, any case) from the catalog and record their ids in
    ``retired_ids``, which no new id reuses. Ids are stable, so nothing is renumbered and no id is
    rewritten: the kept items take ranks 1..n in order, items that lose their only unblocked item are
    rescored, the counts recomputed, and only the catalog is written. Prints the follow-up the catalog
    cannot record by itself: resolved issues to list as close candidates, trackers to revisit, research
    catalog and stub lines naming a retired id (``dangling:``), and other files naming a retired id
    (``reference (not rewritten):``; the snapshots and the history folders, ``artifacts.plans``,
    ``reviews``, ``commit_messages``, ``summaries``, ``scratch`` and each planning prefix, are skipped).
    ``--dry-run`` prints the same report and writes nothing.
``split ID --spec PATH [--dry-run]``
    Replace one item with the parts in the spec file (``{"parts": [{...}, {...}]}``, each a set of field
    overrides laid over a copy of the item; ``title`` required, ``id`` / ``rank`` / ``priority`` refused).
    Every part gets a new id drawn past every live and retired id; the original id joins ``retired_ids``
    and ``split_ids`` records its parts in spec order. Parts inherit the item's links, tracker and close
    candidates; then rescore, re-rank and recount. No id is rewritten: research catalog and stub lines
    naming the split id are listed as ``dangling:`` with its parts, and other files naming it as
    ``reference (not rewritten):``, for a person to point at the right part. A dry run draws its own ids;
    the real run draws again.
``refresh [--dry-run]``
    Rescore every item from ``ranking_method``, re-sort and set each rank to its position, after hand edits
    to item fields. Ids never change and only the catalog is written. A catalog already in order is left
    untouched.
``init``
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
``add --spec PATH [--dry-run] [--file-issue]``
    Add one item per entry of the spec file (``{"items": [{...}, {...}]}``; each holds the fields a person
    judges, never ``id``, ``rank`` or ``priority``, and names its ``issue`` and ``url`` or neither). The
    script draws each item a new stable id past every live and retired id, builds the source
    (``gh_issue``, or for an entry with neither a local-only ``note`` dated today), scores the item,
    re-sorts and recounts; no other id changes and only the catalog is written. A dry run draws its own
    ids; the real run draws again. An issue the catalog already records is refused. ``--file-issue`` files
    a GitHub issue (``gh issue create``, in ``todo.gh.repo`` when set) for each entry that names none, after
    the whole spec passes a dry run, and records it as the ``gh_issue`` source; a failure after filing
    names the issues filed. A dry run files nothing, labels each such item ``(issue to file)`` and prints
    ``would file N issue(s)``.
``migrate-ids [--dry-run] [--exclude PATH]...``
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
    refused. ``--dry-run`` prints the new ids and the files it would rewrite and writes nothing.

``--project`` (default: the git top level of the working directory) and ``--config`` (an alternate
``harness.json``) go before or after the subcommand. A configuration error, an unknown rule id or any
refused operation (render, init, add, retire, split, refresh, migrate-ids, a failed ``gh`` call) exits 2
with one ``problem:`` line on stderr. A catalog still holding ``TODO-NNN`` ids refuses untracked, add,
retire, split and refresh, naming ``migrate-ids``.
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
    sub.add_parser("init", parents=[common], help="Create the TODO folder, an empty catalog and a snapshot.")
    sub.add_parser("untracked", parents=[common], help="List open issues no catalog record mentions.")
    add = sub.add_parser("add", parents=[common], help="Add one item per spec entry: issue or local note.")
    add.add_argument("--spec", type=Path, required=True, help='JSON file: {"items": [{...}, {...}]}.')
    add.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)
    add.add_argument("--file-issue", action="store_true",
                     help="File a GitHub issue for each item that names none, once the spec validates.")
    _migrator(sub, common)
    return parser


def _reshapers(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """``retire``, ``split`` and ``refresh``: the structural edits of a stable-id catalog."""
    ret = sub.add_parser("retire", parents=[common],
                         help="Remove finished items and record their ids as retired.")
    ret.add_argument("ids", nargs="+", help=ID_HELP)
    ret.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)
    spl = sub.add_parser("split", parents=[common], help="Replace one item with parts that get new ids.")
    spl.add_argument("id", help=ID_HELP)
    spl.add_argument("--spec", type=Path, required=True, help='JSON file: {"parts": [{...}, {...}]}.')
    spl.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)
    ref = sub.add_parser("refresh", parents=[common], help="Rescore and re-rank every item.")
    ref.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)


def _migrator(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """``migrate-ids``: the one-time switch from ``TODO-NNN`` to stable ids."""
    mig = sub.add_parser("migrate-ids", parents=[common],
                         help="Give every item a stable id once and rewrite live references; a rerun "
                              "finishes through the stored map")
    mig.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)
    mig.add_argument("--exclude", action="append", default=[], metavar="PATH",
                     help="Leave files under PATH (absolute or relative to the working directory, below "
                          "the project root; matched by path component) as written; repeatable.")


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


def _dispatch(cfg: HarnessConfig, args: argparse.Namespace) -> int:
    if args.command == "check":
        return _check(cfg, args)
    if args.command == "init":
        return _init(cfg)
    if args.command == "untracked":
        return _untracked(cfg)
    if args.command == "add":
        result = apply_add(cfg, args.spec, args.dry_run, file_issues=args.file_issue)
        print("\n".join(reshape_lines(result, args.dry_run)))
        return 0
    if args.command == "render":
        print(render_snapshot(cfg, args.date or dt.date.today()))
    elif args.command == "retire":
        print("\n".join(summary_lines(apply_retirement(cfg, args.ids, args.dry_run), args.dry_run)))
    elif args.command == "split":
        print("\n".join(reshape_lines(apply_split(cfg, args.id, args.spec, args.dry_run), args.dry_run)))
    elif args.command == "refresh":
        print("\n".join(reshape_lines(apply_refresh(cfg, args.dry_run), args.dry_run)))
    elif args.command == "migrate-ids":
        exclude = exclude_paths(cfg, args.exclude, Path.cwd())
        result = apply_migration(cfg, args.dry_run, exclude)
        print("\n".join(migrate_lines(result, args.dry_run)))
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
