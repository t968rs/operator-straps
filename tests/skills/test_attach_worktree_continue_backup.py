"""Behavioral test for the backup a-w takes when ``--continue`` lands over a ``worktree``-ruled dirty path.

The repository under ``tmp_path``: ``main`` has branch ``feature`` checked out and ``wt`` is a detached
worktree cut from it the way ``d-w`` cuts one. The developer edits the ruled dirty path in the target while
the attach is stopped for resolution; the undo the ``--continue`` report prints must bring that edit back.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

pytestmark = pytest.mark.cross_os

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t"}
_WT, _TARGET, _RESOLVED = "one\nWT\nthree\n", "one\nTARGET\nthree\n", "one\nRESOLVED\nthree\n"
_RUN2, _DIRTY, _LATE = '{"run": 2}\n', '{"run": "dirty"}\n', '{"run": "edited during the stop"}\n'


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **_GIT_ENV}
    done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env)
    return done.stdout.strip("\n")


def _write(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")


def _commit(repo: Path, name: str, text: str, message: Optional[str] = None) -> str:
    _write(repo, name, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message or f"edit {name}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture(scope="module")
def script_path(plugin_root: Path) -> Path:
    return plugin_root / "skills" / "a-w" / "commands" / "attach_worktree.py"


@pytest.fixture()
def repos(tmp_path: Path) -> dict:
    """``main`` on ``feature`` holding ``shared.txt`` and ``report.json``; ``wt`` cut from its one commit."""
    main, wt = tmp_path / "main", tmp_path / "wt"
    _git(tmp_path, "init", "-q", "-b", "feature", str(main))
    _write(main, "shared.txt", "one\ntwo\nthree\n")
    base = _commit(main, "report.json", '{"run": 0}\n', "base")
    _git(main, "worktree", "add", "--quiet", "--detach", str(wt), base)
    return {"main": main, "wt": wt, "base": base}


def _run(script_path: Path, repos: dict, *args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(script_path), *args, "--worktree", str(repos["wt"])]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=repos["main"],
                          env={**os.environ, **_GIT_ENV})


def _read(repo: Path, name: str) -> str:
    return (repo / name).read_text(encoding="utf-8")


def test_continue_backs_up_a_ruled_dirty_path_edited_during_the_stop(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _commit(wt, "report.json", _RUN2, "worktree report")
    _commit(wt, "shared.txt", _WT, "worktree edit")
    _commit(main, "shared.txt", _TARGET, "target edit")
    _write(main, "report.json", _DIRTY)
    stop = _run(script_path, repos, "feature", "--auto-resolve", "report.json=worktree")
    assert stop.returncode == 2, stop.stdout + stop.stderr
    _write(main, "report.json", _LATE)
    _write(wt, "shared.txt", _RESOLVED)
    _git(wt, "add", "shared.txt")
    done = _run(script_path, repos, "--continue")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _read(main, "report.json") == _RUN2
    found = re.search(r"--source=([0-9a-f]{7,40}) --worktree", done.stdout)
    assert found, done.stdout
    _git(main, "restore", f"--source={found.group(1)}", "--worktree", "--", "report.json")
    assert _read(main, "report.json") == _LATE
