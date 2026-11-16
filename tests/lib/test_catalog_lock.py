"""The catalog lock: an ``O_CREAT | O_EXCL`` lock file holding a short write lock or a lease.

``hold`` takes the write lock for one read-modify-write (or proceeds under a lease whose token it is given);
``acquire_lease`` / ``release_lease`` hold the file across several processes; ``break_lock`` is the manual
override. A write lock on this host is stale when its pid is dead (or past ``LEASE_STALE_SECONDS``, against a
reused pid); one from another host, or an unreadable one, when older than ``WRITE_STALE_SECONDS``; a lease
only by age (``LEASE_STALE_SECONDS``). A hold removes only a lock that still carries its own token, and a
break removes only the body it judged stale. A busy ``<lock>.break`` guard holds a break off until its
deadline; a guard older than ``WAIT_SECONDS`` is cleared only while its token is unchanged.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

import pytest

from harness_lib import catalog_lock as cl


def _lock(tmp_path: Path) -> Path:
    return tmp_path / "locks" / "docs__TODO__RepoToDo.json.lock"


def _plant(path: Path, **body) -> None:
    """A lock file another process left, with ``body`` over a live write lock of this process."""
    base = {"pid": os.getpid(), "host": socket.gethostname(), "owner": "other", "mode": "write",
            "acquired": time.time()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**base, **body}), encoding="utf-8")


def test_the_constants_match_the_design() -> None:
    assert (cl.WAIT_SECONDS, cl.WRITE_STALE_SECONDS, cl.LEASE_STALE_SECONDS) == (10.0, 60.0, 1800.0)


def test_hold_creates_the_file_and_removes_it(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    with cl.hold(path, "add --inbox"):
        holder = cl.read_holder(path)
        assert holder is not None and holder["mode"] == "write" and holder["owner"] == "add --inbox"
        assert holder["pid"] == os.getpid()
    assert not path.exists()


def test_hold_removes_the_file_when_the_body_raises(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    with pytest.raises(RuntimeError):
        with cl.hold(path, "retire"):
            raise RuntimeError("boom")
    assert not path.exists()


def test_a_live_write_lock_makes_a_second_writer_refuse_naming_the_holder(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    _plant(path, owner="split todo-k7qf")
    with pytest.raises(cl.LockError, match="split todo-k7qf"):
        with cl.hold(path, "add --inbox", wait=0.2):
            pass
    assert cl.read_holder(path)["owner"] == "split todo-k7qf"


def test_a_write_lock_of_another_host_past_its_age_is_broken(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    _plant(path, pid=424242, host="elsewhere", acquired=time.time() - cl.WRITE_STALE_SECONDS - 5)
    with cl.hold(path, "add --inbox", wait=0.2):
        assert cl.read_holder(path)["owner"] == "add --inbox"


def test_a_live_same_host_holder_past_the_write_age_is_kept(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    _plant(path, owner="add --inbox render", acquired=time.time() - cl.WRITE_STALE_SECONDS - 5)
    with pytest.raises(cl.LockError, match="add --inbox render"):
        with cl.hold(path, "retire", wait=0.2):
            pass
    _plant(path, acquired=time.time() - cl.LEASE_STALE_SECONDS - 5)
    with cl.hold(path, "retire", wait=0.2):
        assert cl.read_holder(path)["owner"] == "retire"


def test_a_broken_holder_leaves_its_successor_lock_in_place(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    with cl.hold(path, "slow drain"):
        _plant(path, owner="successor", token="theirs")
    holder = cl.read_holder(path)
    assert holder is not None and holder["owner"] == "successor"


def test_a_break_refuses_a_body_that_changed_since_it_was_read(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    _plant(path, pid=424242, owner="stale", token="old")
    observed = cl.read_holder(path)
    _plant(path, owner="fresh", token="new")
    assert cl.break_if_unchanged(path, observed) is False
    assert cl.read_holder(path)["owner"] == "fresh"
    assert cl.break_if_unchanged(path, cl.read_holder(path)) is True
    assert not path.exists()


def _backdate(path: Path, seconds: float) -> None:
    """Set the mtime of ``path`` to ``seconds`` ago (negative: into the future)."""
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def _guard(path: Path) -> Path:
    return path.with_name(path.name + ".break")


def test_an_unreadable_lock_is_kept_while_fresh_and_broken_past_the_write_age(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"pid": 1, "own', encoding="utf-8")
    with pytest.raises(cl.LockError, match="unreadable"):
        with cl.hold(path, "add --inbox", wait=0.2):
            pass
    assert path.read_text(encoding="utf-8") == '{"pid": 1, "own'
    _backdate(path, cl.WRITE_STALE_SECONDS + 5)
    with cl.hold(path, "add --inbox", wait=0.2):
        assert cl.read_holder(path)["owner"] == "add --inbox"
    assert not path.exists()


def test_a_busy_break_guard_holds_off_the_break(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _lock(tmp_path)
    _plant(path, pid=424242, owner="stale", token="old")
    observed = cl.read_holder(path)
    guard = _guard(path)
    guard.write_text("another breaker", encoding="utf-8")
    _backdate(guard, -60)
    assert cl.break_if_unchanged(path, observed, deadline=time.monotonic()) is False
    monkeypatch.setattr(cl, "WAIT_SECONDS", 0.1)
    with pytest.raises(cl.LockError, match="break guard"):
        cl.break_if_unchanged(path, observed)
    assert cl.read_holder(path) == observed
    assert guard.read_text(encoding="utf-8") == "another breaker"


def test_a_stale_break_guard_is_cleared_and_the_break_proceeds(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    _plant(path, pid=424242, owner="stale", token="old")
    guard = _guard(path)
    guard.write_text("crashed breaker", encoding="utf-8")
    _backdate(guard, cl.WAIT_SECONDS + 5)
    assert cl.break_if_unchanged(path, cl.read_holder(path)) is True
    assert not path.exists() and not guard.exists()


def test_a_stale_guard_replaced_between_its_reads_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch
                                                          ) -> None:
    guard = _guard(_lock(tmp_path))
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text("first", encoding="utf-8")
    _backdate(guard, cl.WAIT_SECONDS + 5)
    reads = iter(["first", "second"])
    monkeypatch.setattr(cl, "_read_text", lambda _path: next(reads))
    assert cl._clear_stale_guard(guard) is False
    assert guard.exists()


def test_a_write_lock_of_a_dead_pid_is_broken(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _lock(tmp_path)
    _plant(path, pid=424242)
    monkeypatch.setattr(cl, "pid_alive", lambda pid: pid != 424242)
    with cl.hold(path, "add --inbox", wait=0.2):
        assert cl.read_holder(path)["owner"] == "add --inbox"


def test_a_write_lock_of_another_host_is_kept_until_its_age(tmp_path: Path, monkeypatch: pytest.MonkeyPatch
                                                             ) -> None:
    path = _lock(tmp_path)
    _plant(path, pid=424242, host="elsewhere")
    monkeypatch.setattr(cl, "pid_alive", lambda pid: False)
    with pytest.raises(cl.LockError):
        with cl.hold(path, "add --inbox", wait=0.2):
            pass


def test_a_lease_blocks_a_plain_writer_and_admits_its_token(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    token = cl.acquire_lease(path, "todo-editor retire")
    assert cl.read_holder(path)["mode"] == "lease"
    with pytest.raises(cl.LockError, match="todo-editor retire"):
        with cl.hold(path, "add --inbox", wait=0.2):
            pass
    with cl.hold(path, "retire", lease=token):
        assert cl.read_holder(path)["mode"] == "lease"
    assert cl.read_holder(path)["mode"] == "lease"
    cl.release_lease(path, token)
    assert not path.exists()


def test_a_wrong_token_is_refused_at_once(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    cl.acquire_lease(path, "todo-editor split")
    started = time.monotonic()
    with pytest.raises(cl.LockError, match="token"):
        with cl.hold(path, "split", lease="not-the-token", wait=5):
            pass
    assert time.monotonic() - started < 2
    with pytest.raises(cl.LockError, match="token"):
        cl.release_lease(path, "not-the-token")


def test_a_token_with_no_lease_is_refused(tmp_path: Path) -> None:
    with pytest.raises(cl.LockError, match="no lease"):
        with cl.hold(_lock(tmp_path), "retire", lease="abc"):
            pass


def test_a_lease_survives_a_dead_pid_and_breaks_by_age(tmp_path: Path, monkeypatch: pytest.MonkeyPatch
                                                       ) -> None:
    path = _lock(tmp_path)
    monkeypatch.setattr(cl, "pid_alive", lambda pid: False)
    _plant(path, mode="lease", token="t1", owner="todo-editor refresh")
    with pytest.raises(cl.LockError):
        with cl.hold(path, "add --inbox", wait=0.2):
            pass
    _plant(path, mode="lease", token="t1", acquired=time.time() - cl.LEASE_STALE_SECONDS - 5)
    with cl.hold(path, "add --inbox", wait=0.2):
        assert cl.read_holder(path)["mode"] == "write"


def test_break_lock_removes_any_lock_and_returns_its_body(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    assert cl.break_lock(path) is None
    token = cl.acquire_lease(path, "todo-editor retire")
    body = cl.break_lock(path)
    assert body is not None and body["token"] == token and not path.exists()


def test_two_leases_do_not_stack(tmp_path: Path) -> None:
    path = _lock(tmp_path)
    cl.acquire_lease(path, "first")
    with pytest.raises(cl.LockError, match="first"):
        cl.acquire_lease(path, "second", wait=0.2)


@pytest.mark.cross_os
def test_pid_alive_reads_this_process_without_signalling_it(monkeypatch: pytest.MonkeyPatch) -> None:
    if sys.platform == "win32":
        def refuse(*_args) -> None:
            raise AssertionError("os.kill terminates the process on Windows")
        monkeypatch.setattr(os, "kill", refuse)
    assert cl.pid_alive(os.getpid()) is True
