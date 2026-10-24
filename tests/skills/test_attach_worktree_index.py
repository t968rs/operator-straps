"""The a-w command ``commands/attach_worktree.py`` keeps the worktree's index and names the conflict recovery.

Each test builds a throwaway repository under ``tmp_path``: ``main`` has branch ``feature`` checked out and
``wt`` is a detached worktree cut from it, with one staged and one unstaged edit and a conflicting target.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.cross_os

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t"}


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **_GIT_ENV}
    done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env)
    return done.stdout.strip()


def _commit(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"edit {name}")


@pytest.fixture()
def conflicted(tmp_path: Path, plugin_root: Path) -> dict:
    """Run a staged attach that conflicts on ``shared.txt``; the worktree also stages ``kept.txt``."""
    main, wt = tmp_path / "main", tmp_path / "wt"
    _git(tmp_path, "init", "-q", "-b", "feature", str(main))
    _commit(main, "shared.txt", "one\ntwo\nthree\n")
    _commit(main, "kept.txt", "kept\n")
    _git(main, "worktree", "add", "--quiet", "--detach", str(wt), "HEAD")
    (wt / "kept.txt").write_text("staged edit\n", encoding="utf-8")
    _git(wt, "add", "kept.txt")
    (wt / "shared.txt").write_text("one\nWORKTREE\nthree\n", encoding="utf-8")
    _commit(main, "shared.txt", "one\nTARGET\nthree\n")
    script = plugin_root / "skills" / "a-w" / "commands" / "attach_worktree.py"
    done = subprocess.run([sys.executable, str(script), "feature", "--worktree", str(wt)],
                          capture_output=True, text=True, cwd=main, env={**os.environ, **_GIT_ENV})
    return {"main": main, "wt": wt, "done": done}


def test_a_conflict_leaves_the_worktree_index_as_it_was(conflicted: dict) -> None:
    wt = conflicted["wt"]
    assert conflicted["done"].returncode == 1
    assert _git(wt, "diff", "--cached", "--name-only").splitlines() == ["kept.txt"]
    assert _git(wt, "diff", "--name-only").splitlines() == ["shared.txt"]


def test_the_conflict_error_names_the_finish_and_undo_commands(conflicted: dict) -> None:
    stderr = conflicted["done"].stderr
    assert "shared.txt" in stderr
    assert f"git worktree remove --force {conflicted['wt'].resolve().as_posix()}" in stderr
    assert f"git -C {conflicted['main'].resolve().as_posix()} reset --hard" in stderr


def test_the_named_undo_restores_a_clean_target(conflicted: dict) -> None:
    main = conflicted["main"]
    _git(main, "reset", "-q", "--hard")
    assert _git(main, "status", "--porcelain") == ""
    assert conflicted["wt"].exists()
