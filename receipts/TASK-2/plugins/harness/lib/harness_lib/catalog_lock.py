"""An ``O_CREAT | O_EXCL`` lock file that holds either a short write lock or a long lease.

``hold`` takes the write lock for one read-modify-write, or proceeds under a lease whose token it is given.
``acquire_lease`` and ``release_lease`` keep the file across several processes; ``break_lock`` is the manual
override. The body is JSON: ``pid``, ``host``, ``owner``, ``mode`` (``write`` or ``lease``), ``acquired``
(epoch seconds) and ``token``.

Staleness:

- a write lock of this host is stale when its pid is dead, or past ``LEASE_STALE_SECONDS`` (the ceiling
  against a reused pid); a live holder is never broken by ``WRITE_STALE_SECONDS``, since one hold may span
  a render, a check and a reference scan;
- a write lock of another host, or an unreadable body (aged by mtime), past ``WRITE_STALE_SECONDS``;
- a lease only past ``LEASE_STALE_SECONDS``.

Every removal of a lock another process may also judge (a stale break, a hold's release, a lease release)
goes through ``break_if_unchanged``: under an ``O_EXCL`` ``<lock>.break`` guard it re-reads the body and
unlinks only the body it observed, so two breakers that read one stale body never remove the fresh lock
one of them created, and a holder that was broken never deletes its successor's lock.

The guard carries a random token and turns stale after ``WAIT_SECONDS`` (a crashed breaker). A breaker
removes a stale guard only when the token read before the age check is read again just before the unlink,
so a guard another breaker created in its place survives. The window left is the moment between that
second read and the unlink, open only once a guard has sat ``WAIT_SECONDS`` without its owner.
"""
from __future__ import annotations

import json
import os
import random
import secrets
import socket
import sys
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Iterator, Optional, Union

WAIT_SECONDS = 10.0
WRITE_STALE_SECONDS = 60.0
LEASE_STALE_SECONDS = 1800.0

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5
_UNLINK_TRIES = 5

PathLike = Union[str, Path]


class LockError(RuntimeError):
    """The lock is held by another owner, or a lease token does not match."""


def _jitter() -> float:
    """A random retry pause of 20 to 120 ms."""
    return random.uniform(0.02, 0.12)


def _unlink(path: Path) -> bool:
    """Remove ``path``; False when it was already gone.

    A reader holding the file open on Windows makes the unlink fail for a moment, so it is retried briefly.
    """
    for attempt in range(_UNLINK_TRIES):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except PermissionError:
            if attempt == _UNLINK_TRIES - 1:
                raise
            time.sleep(_jitter())
    return False


def _mtime_age(path: Path) -> float:
    """Seconds since ``path`` was last written; 0.0 when it cannot be read."""
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return 0.0


def read_holder(path: PathLike) -> Optional[dict]:
    """The lock body at ``path``, or None when the file is missing or does not hold a JSON object."""
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _pid_alive_windows(pid: int) -> bool:
    """Whether ``pid`` runs, by ``OpenProcess`` and ``GetExitCodeProcess``; never signals the process."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def pid_alive(pid: int) -> bool:
    """Whether process ``pid`` runs on this host.

    POSIX probes with signal 0 (a permission refusal means the process exists). Windows queries the process
    handle instead, since ``os.kill`` there terminates the target.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _age(path: Path, body: dict) -> float:
    """Seconds since ``body`` was acquired, by its ``acquired`` stamp or else the file's mtime."""
    acquired = body.get("acquired")
    if isinstance(acquired, (int, float)) and not isinstance(acquired, bool):
        return time.time() - acquired
    return _mtime_age(path)


def _is_stale(path: Path, body: Optional[dict]) -> bool:
    """Whether the lock at ``path`` with ``body`` (None: unreadable) may be broken."""
    if body is None:
        return _present(path) and _mtime_age(path) > WRITE_STALE_SECONDS
    age = _age(path, body)
    if body.get("mode") == "lease":
        return age > LEASE_STALE_SECONDS
    if body.get("host") == socket.gethostname():
        return age > LEASE_STALE_SECONDS or not pid_alive(body.get("pid"))
    return age > WRITE_STALE_SECONDS


def _present(path: Path) -> bool:
    """Whether ``path`` exists, counting a stat refused with PermissionError (Windows delete pending)."""
    try:
        os.stat(str(path))
    except FileNotFoundError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _exclusive_open(path: Path) -> Optional[int]:
    """A descriptor for ``path`` created exclusively; None when the file already exists.

    A PermissionError is retried (None) only on Windows while ``path`` is present, the delete-pending case;
    anywhere else, such as an unwritable folder, it propagates.
    """
    try:
        return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return None
    except PermissionError:
        if sys.platform != "win32" or not _present(path):
            raise
        return None


def _create_with(path: Path, text: str) -> bool:
    """Create ``path`` exclusively holding ``text``; False when it exists.

    A failed write closes and removes the half-made file before the error propagates.
    """
    fd = _exclusive_open(path)
    if fd is None:
        return False
    try:
        os.write(fd, text.encode("utf-8"))
    except OSError:
        os.close(fd)
        with suppress(OSError):
            _unlink(path)
        raise
    os.close(fd)
    return True


def _read_text(path: Path) -> Optional[str]:
    """The text of ``path``, or None when it cannot be read."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _clear_stale_guard(guard: Path) -> bool:
    """Remove ``guard`` when older than ``WAIT_SECONDS`` and still carrying the token read first.

    The token is read before the age check and again just before the unlink, so a guard another breaker
    put in place of the stale one is left alone. Returns whether a guard was removed.
    """
    first = _read_text(guard)
    if first is None or _mtime_age(guard) <= WAIT_SECONDS:
        return False
    if _read_text(guard) != first:
        return False
    return _unlink(guard)


def _take_guard(guard: Path, deadline: float) -> Optional[str]:
    """Create ``guard`` with a fresh token, retrying until ``deadline`` (monotonic); None when still busy."""
    while True:
        token = secrets.token_hex(8)
        if _create_with(guard, token):
            return token
        if _clear_stale_guard(guard):
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(_jitter(), remaining))


def _drop_guard(guard: Path, token: str) -> None:
    """Remove ``guard`` while it still carries ``token``."""
    if _read_text(guard) == token:
        _unlink(guard)


def _unlink_if_same(path: Path, observed: Optional[dict]) -> bool:
    """Unlink ``path`` when its body equals ``observed`` (None: unreadable and stale)."""
    if read_holder(path) != observed:
        return False
    if observed is None and not _is_stale(path, None):
        return False
    return _unlink(path)


def break_if_unchanged(path: PathLike, observed: Optional[dict], deadline: Optional[float] = None) -> bool:
    """Remove the lock at ``path`` only when its body still equals ``observed``.

    ``observed`` None stands for an unreadable body, removed only while it stays unreadable and older than
    ``WRITE_STALE_SECONDS``. ``deadline`` is a ``time.monotonic()`` value bounding the wait for the
    ``<lock>.break`` guard: a guard still busy then returns False. None waits ``2 * WAIT_SECONDS`` and
    raises LockError instead. Returns whether the lock was removed.
    """
    path = Path(path)
    guard = path.with_name(path.name + ".break")
    limit = time.monotonic() + 2 * WAIT_SECONDS if deadline is None else deadline
    token = _take_guard(guard, limit)
    if token is None:
        if deadline is not None:
            return False
        raise LockError(f"break guard {guard} stays busy")
    try:
        return _unlink_if_same(path, observed)
    finally:
        _drop_guard(guard, token)


def break_lock(path: PathLike) -> Optional[dict]:
    """Remove any lock at ``path``; its body, ``{}`` for an unreadable one, or None when there was none."""
    path = Path(path)
    if not path.exists():
        return None
    body = read_holder(path)
    _unlink(path)
    return body if body is not None else {}


def _try_create(path: Path, owner: str, mode: str) -> Optional[str]:
    """Create the lock file exclusively with a fresh body; its token, or None when the file exists."""
    token = secrets.token_hex(8)
    body = {"pid": os.getpid(), "host": socket.gethostname(), "owner": owner, "mode": mode,
            "acquired": time.time(), "token": token}
    return token if _create_with(path, json.dumps(body)) else None


def _busy_message(path: Path, body: Optional[dict]) -> str:
    """The refusal naming the holder's owner, mode and age."""
    if body is None and not os.path.exists(path):
        return f"lock {path} could not be created (access denied or pending delete)"
    if body is None:
        return f"lock {path} is held by an unreadable body ({_mtime_age(path):.0f}s old)"
    return (f"lock {path} is held by {body.get('owner')!r} ({body.get('mode')}, "
            f"{_age(path, body):.0f}s old, pid {body.get('pid')} on {body.get('host')})")


def _acquire(path: Path, owner: str, mode: str, wait: Optional[float]) -> str:
    """Create the lock at ``path`` in ``mode``, breaking a stale holder, retrying until ``wait`` runs out."""
    limit = WAIT_SECONDS if wait is None else wait
    deadline = time.monotonic() + limit
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        token = _try_create(path, owner, mode)
        if token is not None:
            return token
        observed = read_holder(path)
        if _is_stale(path, observed) and break_if_unchanged(path, observed, deadline):
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LockError(_busy_message(path, observed))
        time.sleep(min(_jitter(), remaining))


def _release_own(path: Path, token: str) -> None:
    """Remove the write lock at ``path`` only while its body still carries ``token``."""
    body = read_holder(path)
    if body is not None and body.get("token") == token:
        break_if_unchanged(path, body)


def check_lease(path: PathLike, token: str) -> dict:
    """The lease body at ``path`` when it carries ``token``; LockError naming 'no lease' or 'token'."""
    path = Path(path)
    body = read_holder(path)
    if body is None or body.get("mode") != "lease":
        held = "" if body is None else f" (held by {body.get('owner')!r} in {body.get('mode')} mode)"
        raise LockError(f"no lease at {path} for the given token{held}")
    if body.get("token") != token:
        raise LockError(f"lease at {path} held by {body.get('owner')!r} carries another token")
    return body


@contextmanager
def hold(path: PathLike, owner: str, lease: Optional[str] = None,
         wait: Optional[float] = None) -> Iterator[None]:
    """Run the body under the write lock at ``path``, or under the lease ``lease`` names.

    With ``lease`` the file must hold a lease carrying that token (LockError at once otherwise), and the
    file is left as it is. Without it the write lock is created, waiting up to ``wait`` seconds
    (``WAIT_SECONDS`` when None), and removed afterwards only while it still carries this hold's token.
    A release that fails while the body raises is noted on the body's exception instead of replacing it.
    """
    path = Path(path)
    if lease is not None:
        check_lease(path, lease)
        yield
        return
    token = _acquire(path, owner, "write", wait)
    try:
        yield
    except BaseException as exc:
        try:
            _release_own(path, token)
        except (LockError, OSError) as rel:
            exc.add_note(f"lock {path} was not released: {rel}")
        raise
    _release_own(path, token)


def acquire_lease(path: PathLike, owner: str, wait: Optional[float] = None) -> str:
    """Take a lease on ``path`` for ``owner`` and return its token; a held lease or write lock refuses."""
    return _acquire(Path(path), owner, "lease", wait)


def release_lease(path: PathLike, token: str) -> None:
    """Remove the lease at ``path`` that carries ``token``; LockError naming 'token' otherwise."""
    path = Path(path)
    body = check_lease(path, token)
    if not break_if_unchanged(path, body):
        raise LockError(f"lease at {path} changed before its release with this token")
