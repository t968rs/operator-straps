"""``todo_sync.py lease acquire --wait SECONDS``: a lease run waits longer than the write lock's default
before it refuses, so a split that finds another split's lease held waits for it instead of ending.

Run in-process; projects come from ``tests/lib/_todo_helpers.py``. The default wait shrinks to 0.2 s, so a
lease taken after a longer wait proves the option took effect.
"""
from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path
from typing import List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _todo_helpers import build  # noqa: E402
from conftest import PLUGIN_ROOT  # noqa: E402
from harness_lib import catalog_lock  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, locking  # noqa: E402

WALK_ROOTS = ()


@pytest.fixture(scope="module")
def driver():
    script = PLUGIN_ROOT / "scripts" / "todo_sync.py"
    spec = importlib.util.spec_from_file_location("todo_sync_lease_wait_driver", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def short_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog_lock, "WAIT_SECONDS", 0.2)


def _parse(driver, argv: List[str]):
    """The parsed arguments; a parser refusal fails the test instead of exiting."""
    try:
        return driver._parser().parse_args(argv)
    except SystemExit:
        raise AssertionError(f"todo_sync.py rejects {argv}") from None


def _free_later(cfg, token: str, delay: float) -> threading.Timer:
    """Free the lease ``token`` names after ``delay`` seconds, from another thread."""
    timer = threading.Timer(delay, locking.free, args=(cfg, token))
    timer.start()
    return timer


def test_acquire_waits_past_the_default_for_a_lease_freed_meanwhile(make_project) -> None:
    cfg = build(make_project)
    held = locking.acquire(cfg, "todo-editor split")
    timer = _free_later(cfg, held, 0.6)
    try:
        token = locking.acquire(cfg, "todo-editor split", wait=10)
    finally:
        timer.join()
    assert token and token != held
    locking.free(cfg, token)


def test_acquire_refuses_once_its_own_wait_runs_out(make_project) -> None:
    cfg = build(make_project)
    held = locking.acquire(cfg, "todo-editor split")
    started = time.monotonic()
    with pytest.raises(TodoSyncError, match="todo-editor split"):
        locking.acquire(cfg, "another split", wait=0.6)
    assert time.monotonic() - started >= 0.5
    locking.free(cfg, held)


def test_lease_acquire_takes_a_wait_in_seconds(driver) -> None:
    args = _parse(driver, ["lease", "acquire", "--owner", "todo-editor split", "--wait", "300"])
    assert args.wait == 300


def test_the_wait_defaults_to_the_lock_wait(driver) -> None:
    args = _parse(driver, ["lease", "acquire", "--owner", "todo-editor split"])
    assert getattr(args, "wait", "missing") is None


@pytest.mark.parametrize("value", ["-1", "soon", "inf", "1e999"])
def test_the_wait_is_a_non_negative_number(driver, capsys, value: str) -> None:
    with pytest.raises(SystemExit):
        driver._parser().parse_args(["lease", "acquire", "--owner", "x", "--wait", value])
    err = capsys.readouterr().err
    assert "unrecognized" not in err and "--wait" in err


def test_the_driver_waits_for_the_held_lease(driver, make_project, capsys) -> None:
    cfg = build(make_project)
    _parse(driver, ["lease", "acquire", "--owner", "todo-editor split", "--wait", "10"])
    held = locking.acquire(cfg, "todo-editor split")
    timer = _free_later(cfg, held, 0.6)
    try:
        code = driver.main(["--project", str(cfg.project_root), "lease", "acquire", "--owner",
                            "todo-editor split", "--wait", "10"])
    finally:
        timer.join()
    out = capsys.readouterr()
    assert code == 0, out.err
    assert out.out.startswith("lease: ")
