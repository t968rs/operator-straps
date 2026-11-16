"""The TODO catalog's lock, as the ``todo_sync.py`` driver takes it.

One lock file per catalog, ``<state_dir>/locks/<catalog path with '/' as '__'>.lock`` (``catalog_lock``
holds the protocol). ``guard`` runs one catalog write under the write lock, or under a lease whose token
the caller passes; ``acquire`` and ``release`` bracket a lease across several commands, and ``release``
recounts the catalog, renders the snapshot and runs the check before the lease is freed. ``leased`` wraps
one command in a lease of its own, freed by ``free`` without that recount, or in the held lease a passed
token names. ``break_`` is the manual
override. Every ``LockError`` leaves this module as a ``TodoSyncError``.
"""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional

from harness_lib import catalog_lock
from harness_lib.config import HarnessConfig
from harness_lib.todo_sync import TodoSyncError, check, render_snapshot, report_path, write_report
from harness_lib.todo_sync.retire import dump_like, load_catalog, recount, write_edits
from harness_lib.todo_sync.sources import posix


def lock_path(cfg: HarnessConfig) -> Path:
    """Absolute path of the catalog's lock file under ``<state_dir>/locks``.

    Raises:
        TodoSyncError: no catalog configured (``todo.folder`` null).
    """
    if not cfg.todo.catalog:
        raise TodoSyncError("the catalog lock needs todo.folder")
    name = posix(cfg.todo.catalog).strip("/").replace("/", "__") + ".lock"
    return cfg.path(cfg.state_dir) / "locks" / name


@contextmanager
def guard(cfg: HarnessConfig, owner: str, lease: Optional[str] = None) -> Iterator[None]:
    """Run the body under the catalog's write lock, or under the lease ``lease`` names.

    With no catalog configured the body runs unlocked: there is no catalog to protect, and the write it
    guards refuses on its own.

    Raises:
        TodoSyncError: another owner holds the lock past the wait, or ``lease`` names no held lease.
    """
    if not cfg.todo.catalog:
        yield
        return
    try:
        with catalog_lock.hold(lock_path(cfg), owner, lease):
            yield
    except catalog_lock.LockError as exc:
        raise TodoSyncError(str(exc)) from exc


def acquire(cfg: HarnessConfig, owner: str) -> str:
    """Take a lease on the catalog for ``owner``; its token.

    Raises:
        TodoSyncError: a lease or write lock is held past the wait.
    """
    try:
        return catalog_lock.acquire_lease(lock_path(cfg), owner)
    except catalog_lock.LockError as exc:
        raise TodoSyncError(str(exc)) from exc


def free(cfg: HarnessConfig, token: str) -> None:
    """Remove the lease carrying ``token`` without the recount ``release`` runs.

    Raises:
        TodoSyncError: no lease, another token, or a lease that changed before its removal.
    """
    try:
        catalog_lock.release_lease(lock_path(cfg), token)
    except catalog_lock.LockError as exc:
        raise TodoSyncError(str(exc)) from exc


def _free_noting(cfg: HarnessConfig, token: str, exc: BaseException) -> None:
    """Free the lease while ``exc`` propagates; a failed free is noted on ``exc`` instead of replacing it."""
    try:
        free(cfg, token)
    except (TodoSyncError, OSError) as rel:
        exc.add_note(f"lease not freed: {rel}")


@contextmanager
def leased(cfg: HarnessConfig, owner: str, lease: Optional[str] = None) -> Iterator[None]:
    """Run the body under a lease of its own, freed afterwards without the recount (``migrate-ids``).

    With ``lease`` the body runs under the held lease that token names, which is neither taken nor freed
    here, as under ``guard``. With no catalog configured the body runs unlocked, as under ``guard``.

    Raises:
        TodoSyncError: a lease or write lock is held past the wait, or ``lease`` names no held lease.
    """
    if not cfg.todo.catalog or lease is not None:
        with guard(cfg, owner, lease):
            yield
        return
    token = acquire(cfg, owner)
    try:
        yield
    except BaseException as exc:
        _free_noting(cfg, token, exc)
        raise
    free(cfg, token)


def _recount(cfg: HarnessConfig) -> str:
    """Recount the catalog alone (no rescore, no rerank), writing it only when the text changes; the head
    of the release line."""
    raw, data = load_catalog(cfg, "lease release")
    data["counts"] = recount(data.get("counts"), data, ())
    text = dump_like(data, raw)
    if text == raw:
        return "counts unchanged"
    write_edits(cfg, text)
    return "counts updated"


def _settle(cfg: HarnessConfig) -> List[str]:
    """Recount, render the snapshot when ``todo.snapshots.dir`` is set, run the check and write its report."""
    lines = [f"lease released; {_recount(cfg)}"]
    if cfg.todo.snapshots.dir:
        snap = render_snapshot(cfg, dt.date.today())
        lines.append(f"rendered {posix(str(snap.relative_to(cfg.project_root)))}")
    report = check(cfg)
    write_report(report, report_path(cfg))
    lines.append(f"check drift={report.drift}")
    return lines


def release(cfg: HarnessConfig, token: str) -> List[str]:
    """End the lease ``token`` names: recount, render and check, then free the lease even when those fail.

    Returns:
        The lines to print: ``lease released; <counts updated|counts unchanged>``, a ``rendered <path>``
        line when a snapshot was written, and ``check drift=<d>`` last.

    Raises:
        TodoSyncError: a wrong token or no lease (nothing freed), or a recount, render or check failure
            (the lease is freed regardless; a failed free is noted on that error, not raised over it).
    """
    try:
        catalog_lock.check_lease(lock_path(cfg), token)
    except catalog_lock.LockError as exc:
        raise TodoSyncError(str(exc)) from exc
    try:
        lines = _settle(cfg)
    except BaseException as exc:
        _free_noting(cfg, token, exc)
        raise
    free(cfg, token)
    return lines


def break_(cfg: HarnessConfig) -> Optional[dict]:
    """Remove whatever lock the catalog holds; its body (``{}`` when unreadable), or None when none was
    held."""
    return catalog_lock.break_lock(lock_path(cfg))
