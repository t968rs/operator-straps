"""The TODO inbox: drafted ``add`` items wait here, one file per item, until a drain adds them to the catalog.

``put`` validates a whole ``add`` spec against the catalog (a dry run), files the issues asked for, then
writes each item to ``<scratch_folder>/todo-inbox/<stamp>-<NN>-<hex>.json`` without touching the catalog.
``drain`` adds every inbox file to the catalog in one write, oldest first, deletes the accepted files, keeps
each rejected one as ``<stem>.rejected.json`` beside a ``<stem>.reason.txt``, then renders the snapshot and
runs the check. The caller holds the catalog lock around a drain; ``drain`` takes none.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import random
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from harness_lib.config import HarnessConfig
from harness_lib.todo_sync import TodoSyncError, check, render_snapshot, report_path
from harness_lib.todo_sync import report as _report
from harness_lib.todo_sync import reshape
from harness_lib.todo_sync.ranking import RankingError
from harness_lib.todo_sync.report import write_atomic, write_report
from harness_lib.todo_sync.reshape import add_items, read_spec
from harness_lib.todo_sync.retire import dump_like, load_catalog, write_edits

REJECTED_SUFFIX = ".rejected.json"
REASON_SUFFIX = ".reason.txt"

Added = Tuple[Tuple[str, Optional[int]], ...]
Filed = Tuple[Tuple[int, str], ...]


@dataclass(frozen=True)
class PutResult:
    """The inbox files ``put`` wrote, in spec order, and the issues it filed (number, URL)."""

    paths: Tuple[Path, ...]
    filed: Filed = ()


@dataclass(frozen=True)
class DrainResult:
    """What a drain added ``(id, issue or None)``, the files it refused ``(name, reason)`` and the check's
    drift (``None`` when nothing landed)."""

    added: Added = ()
    rejected: Tuple[Tuple[str, str], ...] = ()
    drift: Optional[int] = None


def inbox_dir(cfg: HarnessConfig) -> Path:
    """Absolute folder of the project's TODO inbox."""
    return cfg.path(cfg.todo_inbox())


def _stamp() -> str:
    """The current UTC time as ``%Y%m%dT%H%M%S%fZ``."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _pending(specs: Sequence[Any], file_issues: bool) -> List[int]:
    """Indices of the spec items an issue gets filed for: with ``file_issues``, each dict naming none."""
    if not file_issues:
        return []
    return [n for n, s in enumerate(specs) if isinstance(s, dict) and "issue" not in s]


def _validate(cfg: HarnessConfig, specs: Sequence[Any], pending: Sequence[int],
              rng: Optional[random.Random]) -> None:
    """Dry-run the whole spec against the catalog; a refusal raises ``TodoSyncError``."""
    _raw, data = load_catalog(cfg, "add")
    day = dt.date.today().isoformat()
    try:
        if pending:
            reshape._preview_add(data, specs, pending, day, rng)
        else:
            add_items(data, specs, day, rng)
    except RankingError as exc:
        raise TodoSyncError(str(exc)) from exc


def _hidden(path: Path) -> Path:
    """``path`` under a leading-dot name, which a drain skips."""
    return path.with_name("." + path.name)


def _write_items(cfg: HarnessConfig, items: Sequence[Any]) -> Tuple[Path, ...]:
    """Write each item as ``{"items": [item]}`` under one stamp, its zero-padded spec index next, so the
    names sort in spec order even when the clock repeats a stamp.

    Every item is written under a hidden name first and only then renamed, so a drain never sees part of a
    put; on any failure every file written so far (hidden or renamed) is deleted and the error re-raised.
    """
    folder, stamp = inbox_dir(cfg), _stamp()
    width = max(2, len(str(len(items) - 1)))
    finals = [folder / f"{stamp}-{n:0{width}d}-{secrets.token_hex(3)}.json" for n in range(len(items))]
    written: List[Path] = []
    try:
        for final, item in zip(finals, items):
            written.append(_hidden(final))
            write_atomic(_hidden(final), json.dumps({"items": [item]}, indent=2, ensure_ascii=False) + "\n")
        for final in finals:
            written.append(final)
            _report._replace_with_retry(str(_hidden(final)), final)
    except BaseException:
        for path in written:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        raise
    return tuple(finals)


def put(cfg: HarnessConfig, spec: Path, file_issues: bool = False,
        rng: Optional[random.Random] = None) -> PutResult:
    """Validate the ``add`` spec ``spec`` against the catalog, file the issues asked for, then write one
    inbox file per item; the catalog is never written. A put is all or nothing: a failed inbox write
    leaves nothing queued.

    Raises:
        TodoSyncError: an unreadable spec, an item the catalog refuses (nothing is filed or written), a
            failed filing, or a failed inbox write after filing (naming the issues already filed).
    """
    specs = read_spec(spec, "items")
    pending = _pending(specs, file_issues)
    _validate(cfg, specs, pending, rng)
    items: Sequence[Any] = specs
    filed: Filed = ()
    if pending:
        items, filed = reshape._file_pending(cfg, specs, pending)
    try:
        paths = _write_items(cfg, items)
    except (OSError, TodoSyncError) as exc:
        if not filed:
            raise
        raise TodoSyncError(reshape._with_filed(str(exc), filed)) from exc
    return PutResult(paths, filed)


def queued(cfg: HarnessConfig) -> List[Path]:
    """The inbox files waiting for a drain, oldest (by name) first; temp and rejected files are skipped."""
    folder = inbox_dir(cfg)
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir()
                   if p.is_file() and p.name.endswith(".json") and not p.name.startswith(".")
                   and not p.name.endswith(REJECTED_SUFFIX)), key=lambda p: p.name)


def _absorb(files: Sequence[Path], working: Dict[str, Any], day: str, rng: Optional[random.Random]
            ) -> Tuple[Dict[str, Any], List[Path], Added, List[Tuple[Path, str]]]:
    """Add each file's items to ``working`` in turn; ``(catalog, accepted files, added, rejected)``."""
    accepted: List[Path] = []
    added: List[Tuple[str, Optional[int]]] = []
    rejected: List[Tuple[Path, str]] = []
    for path in files:
        try:
            out = add_items(working, read_spec(path, "items"), day, rng)
        except (TodoSyncError, RankingError, ValueError) as exc:
            rejected.append((path, str(exc)))
            continue
        working = out.catalog
        accepted.append(path)
        added.extend(out.added)
    return working, accepted, tuple(added), rejected


def _probe(data: Dict[str, Any]) -> None:
    """Rescore the whole catalog once, so a catalog-level fault stops the drain before any inbox file is
    blamed for it."""
    try:
        reshape.refresh_items(data)
    except (RankingError, ValueError) as exc:
        raise TodoSyncError(f"catalog cannot be ranked: {exc}") from exc


def _unlink_with_retry(path: Path) -> None:
    """Delete ``path``, retrying ``PermissionError`` as ``report._replace_with_retry`` does; the last
    failure propagates."""
    attempts = _report.REPLACE_ATTEMPTS
    for attempt in range(1, attempts + 1):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == attempts:
                raise
            time.sleep(_report.REPLACE_DELAY_SECONDS)


def _remove_accepted(paths: Sequence[Path]) -> List[Path]:
    """Delete every accepted inbox file; the ones that could not be deleted."""
    left: List[Path] = []
    for path in paths:
        try:
            _unlink_with_retry(path)
        except OSError:
            left.append(path)
    return left


def _set_aside(path: Path, reason: str) -> None:
    """Rename a refused inbox file to ``<stem>.rejected.json`` and write ``<stem>.reason.txt`` beside it."""
    stem = path.name[:-len(".json")]
    write_atomic(path.with_name(stem + REASON_SUFFIX), reason.rstrip("\n") + "\n")
    _report._replace_with_retry(str(path), path.with_name(stem + REJECTED_SUFFIX))


def _set_aside_all(rejected: Sequence[Tuple[Path, str]]) -> List[Path]:
    """Set every refused file aside; the ones that could not be."""
    stuck: List[Path] = []
    for path, reason in rejected:
        try:
            _set_aside(path, reason)
        except OSError:
            stuck.append(path)
    return stuck


def _problems(left: Sequence[Path], stuck: Sequence[Path]) -> List[str]:
    """The sentences naming inbox files a drain could not delete or set aside."""
    out: List[str] = []
    if left:
        out.append(f"inbox file(s) {', '.join(p.name for p in left)} are already in the catalog but could "
                   "not be deleted: delete them before the next drain")
    if stuck:
        out.append(f"refused inbox file(s) {', '.join(p.name for p in stuck)} could not be set aside; "
                   "the next drain refuses them again")
    return out


def _finish(cfg: HarnessConfig, day: dt.date, landed: bool, left: Sequence[Path],
            stuck: Sequence[Path]) -> Optional[int]:
    """Run the follow-up when items landed, then raise one ``TodoSyncError`` naming every failure; the
    drift (``None`` when nothing landed)."""
    drift: Optional[int] = None
    failure: Optional[Exception] = None
    if landed:
        try:
            drift = _follow_up(cfg, day)
        except (TodoSyncError, OSError) as exc:
            failure = exc
    problems = _problems(left, stuck)
    if failure is not None and not problems:
        raise failure
    if failure is not None or problems:
        head = [str(failure)] if failure is not None else []
        raise TodoSyncError("; ".join(head + problems)) from failure
    return drift


def _follow_up(cfg: HarnessConfig, day: dt.date) -> int:
    """Render the snapshot (when ``todo.snapshots.dir`` is set), run the check, write its report; the
    drift."""
    if cfg.todo.snapshots.dir:
        render_snapshot(cfg, day)
    report = check(cfg)
    write_report(report, report_path(cfg))
    return report.drift


def drain(cfg: HarnessConfig, today: Optional[dt.date] = None,
          rng: Optional[random.Random] = None) -> DrainResult:
    """Add every inbox file to the catalog in one write, oldest first, then delete the accepted files, set
    each refused one aside with its reason, render the snapshot and run the check. The caller holds the
    catalog lock.

    Raises:
        TodoSyncError: an unreadable catalog or one that cannot be ranked (the inbox is left untouched); a
            render, check or report failure after the items landed (their files are already gone, so the
            next drain never adds them again); or accepted files that could not be deleted (named, to be
            deleted before the next drain) or refused files that could not be set aside, raised once the
            rest of the drain has run. When items landed, the message opens with the ids added.
    """
    day = today or dt.date.today()
    files = queued(cfg)
    if not files:
        return DrainResult()
    raw, data = load_catalog(cfg, "add")
    _probe(data)
    working, accepted, added, rejected = _absorb(files, data, day.isoformat(), rng)
    left: List[Path] = []
    if accepted:
        write_edits(cfg, dump_like(working, raw))
        left = _remove_accepted(accepted)
    stuck = _set_aside_all(rejected)
    try:
        drift = _finish(cfg, day, bool(accepted), left, stuck)
    except (TodoSyncError, OSError) as exc:
        if not accepted:
            raise
        raise TodoSyncError(f"inbox: added {_added_text(added)}, then: {exc}") from exc
    refused = tuple((path.name, reason) for path, reason in rejected)
    return DrainResult(added if accepted else (), refused, drift)


def _added_text(added: Added) -> str:
    return ", ".join(f"{new} ({f'#{issue}' if issue is not None else 'note'})" for new, issue in added)


def drain_lines(result: DrainResult) -> List[str]:
    """The drain's one-line report: what landed, what was refused, and the check's drift."""
    if not result.added and not result.rejected:
        return ["inbox: empty"]
    names = ", ".join(name for name, _ in result.rejected)
    refused = f"rejected {len(result.rejected)} ({names})"
    if not result.added:
        return [f"inbox: {refused}"]
    line = f"inbox: added {len(result.added)} item(s): {_added_text(result.added)}"
    if result.rejected:
        line += f"; {refused}"
    return [f"{line}; check drift={result.drift}"]
