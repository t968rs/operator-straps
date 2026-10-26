"""Behavioral tests for the harness a-w skill command ``commands/attach_worktree.py``.

Every test builds a throwaway repository under ``tmp_path``: ``main`` is the checkout where the target branch
``feature`` is checked out, and ``wt`` is a detached worktree cut from it the way ``d-w`` cuts one.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

pytestmark = pytest.mark.cross_os

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **_GIT_ENV}
    done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env)
    return done.stdout.strip()


def _commit(repo: Path, name: str, text: str, message: Optional[str] = None) -> str:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message or f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture(scope="module")
def script_path(plugin_root: Path) -> Path:
    return plugin_root / "skills" / "a-w" / "commands" / "attach_worktree.py"


@pytest.fixture()
def repos(tmp_path: Path) -> dict:
    """``main`` on branch ``feature`` with one commit, and a detached worktree ``wt`` cut from it."""
    main = tmp_path / "main"
    _git(tmp_path, "init", "-q", "-b", "feature", str(main))
    base = _commit(main, "shared.txt", "one\ntwo\nthree\n", "base")
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "--quiet", "--detach", str(wt), base)
    return {"main": main, "wt": wt, "base": base}


def _run(script_path: Path, repos: dict, *args: str,
         cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(script_path), *args]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or repos["main"],
                          env={**os.environ, **_GIT_ENV})


def _attach(script_path: Path, repos: dict, *flags: str) -> subprocess.CompletedProcess:
    return _run(script_path, repos, "feature", "--worktree", str(repos["wt"]), *flags)


def _worktrees(main: Path) -> list:
    out = _git(main, "worktree", "list", "--porcelain")
    return [line for line in out.splitlines() if line.startswith("worktree ")]


def _staged(main: Path) -> list:
    return _git(main, "diff", "--cached", "--name-only").splitlines()


def test_committed_fast_forwards_the_target_keeping_commit_structure(script_path: Path, repos: dict) -> None:
    wt, main = repos["wt"], repos["main"]
    _commit(wt, "a.txt", "a", "first")
    head = _commit(wt, "b.txt", "b", "second")
    done = _attach(script_path, repos, "--committed")
    assert done.returncode == 0, done.stderr
    assert _git(main, "rev-parse", "HEAD") == head
    assert _git(main, "log", "--format=%s", "-2").splitlines() == ["second", "first"]
    assert _git(main, "status", "--porcelain") == ""


def test_committed_removes_the_worktree_without_asking(script_path: Path, repos: dict) -> None:
    _commit(repos["wt"], "a.txt", "a")
    done = _attach(script_path, repos, "--committed")
    assert done.returncode == 0, done.stderr
    assert not repos["wt"].exists()
    assert len(_worktrees(repos["main"])) == 1
    assert "removed worktree" in done.stdout


def test_committed_refuses_when_the_target_moved(script_path: Path, repos: dict) -> None:
    _commit(repos["wt"], "a.txt", "a")
    moved = _commit(repos["main"], "other.txt", "other")
    done = _attach(script_path, repos, "--committed")
    assert done.returncode == 1
    assert "moved" in done.stderr and "staged" in done.stderr
    assert _git(repos["main"], "rev-parse", "HEAD") == moved
    assert repos["wt"].exists()


def test_committed_refuses_uncommitted_worktree_changes(script_path: Path, repos: dict) -> None:
    _commit(repos["wt"], "a.txt", "a")
    (repos["wt"] / "loose.txt").write_text("loose", encoding="utf-8")
    done = _attach(script_path, repos, "--committed")
    assert done.returncode == 1
    assert "uncommitted" in done.stderr
    assert repos["wt"].exists()
    assert _git(repos["main"], "rev-parse", "HEAD") == repos["base"]


def test_committed_without_commits_is_an_error(script_path: Path, repos: dict) -> None:
    done = _attach(script_path, repos, "--committed")
    assert done.returncode == 1
    assert "no commits" in done.stderr
    assert repos["wt"].exists()


def test_staged_default_stages_commits_edits_and_new_files_without_committing(script_path: Path,
                                                                             repos: dict) -> None:
    wt, main = repos["wt"], repos["main"]
    _commit(wt, "a.txt", "a")
    (wt / "shared.txt").write_text("one\nTWO\nthree\n", encoding="utf-8")
    (wt / "fresh.txt").write_text("fresh", encoding="utf-8")
    done = _attach(script_path, repos)
    assert done.returncode == 0, done.stderr
    assert _git(main, "rev-parse", "HEAD") == repos["base"], "staging never commits on the target"
    assert sorted(_staged(main)) == ["a.txt", "fresh.txt", "shared.txt"]
    assert (main / "shared.txt").read_text(encoding="utf-8") == "one\nTWO\nthree\n"
    assert not wt.exists()


def test_staged_merges_three_way_when_the_target_moved(script_path: Path, repos: dict) -> None:
    wt, main = repos["wt"], repos["main"]
    (wt / "shared.txt").write_text("one\ntwo\nTHREE\n", encoding="utf-8")
    _commit(main, "shared.txt", "ONE\ntwo\nthree\n", "target edit")
    moved = _git(main, "rev-parse", "HEAD")
    done = _attach(script_path, repos)
    assert done.returncode == 0, done.stderr
    assert _git(main, "rev-parse", "HEAD") == moved
    assert (main / "shared.txt").read_text(encoding="utf-8") == "ONE\ntwo\nTHREE\n"
    assert not wt.exists()


def test_staged_conflict_stops_and_keeps_the_worktree(script_path: Path, repos: dict) -> None:
    wt, main = repos["wt"], repos["main"]
    (wt / "shared.txt").write_text("one\nWORKTREE\nthree\n", encoding="utf-8")
    _commit(main, "shared.txt", "one\nTARGET\nthree\n", "target edit")
    moved = _git(main, "rev-parse", "HEAD")
    done = _attach(script_path, repos)
    assert done.returncode == 1
    assert "conflicts in shared.txt" in done.stderr, "the conflict branch, not the generic apply failure"
    assert _git(main, "rev-parse", "HEAD") == moved
    assert _git(main, "diff", "--name-only", "--diff-filter=U").splitlines() == ["shared.txt"]
    assert "<<<<<<<" in (main / "shared.txt").read_text(encoding="utf-8")
    assert wt.exists()
    assert (wt / "shared.txt").read_text(encoding="utf-8") == "one\nWORKTREE\nthree\n"
    assert _git(wt, "diff", "--cached") == "", "the worktree's own index is untouched"


def test_staged_moves_a_deletion(script_path: Path, repos: dict) -> None:
    wt, main = repos["wt"], repos["main"]
    (wt / "shared.txt").unlink()
    done = _attach(script_path, repos)
    assert done.returncode == 0, done.stderr
    assert _git(main, "diff", "--cached", "--name-status") == "D\tshared.txt"
    assert not (main / "shared.txt").exists()


def test_staged_moves_a_rename(script_path: Path, repos: dict) -> None:
    wt, main = repos["wt"], repos["main"]
    (wt / "shared.txt").rename(wt / "renamed.txt")
    done = _attach(script_path, repos)
    assert done.returncode == 0, done.stderr
    status = _git(main, "diff", "--cached", "--name-status", "-M").split("\t")
    assert status[0].startswith("R") and status[1:] == ["shared.txt", "renamed.txt"]
    assert (main / "renamed.txt").read_text(encoding="utf-8") == "one\ntwo\nthree\n"


def test_a_target_branch_checked_out_in_the_worktree_itself_is_refused(script_path: Path,
                                                                       repos: dict) -> None:
    _git(repos["wt"], "switch", "-q", "-c", "side")
    done = _run(script_path, repos, "side", "--worktree", str(repos["wt"]))
    assert done.returncode == 1
    assert "worktree itself" in done.stderr
    assert repos["wt"].exists()


def test_staged_with_nothing_to_move_is_an_error(script_path: Path, repos: dict) -> None:
    done = _attach(script_path, repos)
    assert done.returncode == 1
    assert "nothing to move" in done.stderr
    assert repos["wt"].exists()


def test_a_dirty_target_checkout_is_refused(script_path: Path, repos: dict) -> None:
    _commit(repos["wt"], "a.txt", "a")
    (repos["main"] / "shared.txt").write_text("dirty\n", encoding="utf-8")
    done = _attach(script_path, repos)
    assert done.returncode == 1
    assert "not clean" in done.stderr
    assert repos["wt"].exists()


def test_a_target_branch_checked_out_nowhere_is_refused(script_path: Path, repos: dict) -> None:
    _git(repos["main"], "switch", "-q", "-c", "elsewhere")
    _commit(repos["wt"], "a.txt", "a")
    done = _attach(script_path, repos)
    assert done.returncode == 1
    assert "feature" in done.stderr and "not checked out" in done.stderr
    assert repos["wt"].exists()


def test_the_main_checkout_is_not_a_worktree_to_attach(script_path: Path, repos: dict) -> None:
    done = _run(script_path, repos, "feature", "--worktree", str(repos["main"]))
    assert done.returncode == 1
    assert "linked worktree" in done.stderr


def test_the_worktree_defaults_to_the_current_directory(script_path: Path, repos: dict) -> None:
    head = _commit(repos["wt"], "a.txt", "a")
    done = _run(script_path, repos, "feature", "--committed", cwd=repos["wt"])
    assert done.returncode == 0, done.stderr
    assert _git(repos["main"], "rev-parse", "HEAD") == head
    assert not repos["wt"].exists()


@pytest.mark.parametrize("spelling", ["--target-branch", "--target_branch"])
def test_target_branch_flag_spellings_match_the_positional(script_path: Path, repos: dict,
                                                          spelling: str) -> None:
    head = _commit(repos["wt"], "a.txt", "a")
    done = _run(script_path, repos, spelling, "feature", "--worktree", str(repos["wt"]), "--committed")
    assert done.returncode == 0, done.stderr
    assert _git(repos["main"], "rev-parse", "HEAD") == head


def test_head_names_the_main_checkouts_branch_for_a_staged_move(script_path: Path, repos: dict) -> None:
    _commit(repos["wt"], "a.txt", "a")
    done = _run(script_path, repos, "HEAD", "--worktree", str(repos["wt"]))
    assert done.returncode == 0, done.stderr
    assert "staged 1 file(s) on feature" in done.stdout
    assert _staged(repos["main"]) == ["a.txt"]
    assert not repos["wt"].exists()


def test_head_names_the_main_checkouts_branch_for_a_committed_move(script_path: Path, repos: dict) -> None:
    head = _commit(repos["wt"], "a.txt", "a")
    done = _run(script_path, repos, "HEAD", "--worktree", str(repos["wt"]), "--committed")
    assert done.returncode == 0, done.stderr
    assert f"attached 1 commit(s) to feature at {head[:7]}" in done.stdout
    assert _git(repos["main"], "rev-parse", "HEAD") == head


def test_head_from_inside_the_worktree_still_targets_the_main_checkout(script_path: Path,
                                                                      repos: dict) -> None:
    head = _commit(repos["wt"], "a.txt", "a")
    done = _run(script_path, repos, "HEAD", "--committed", cwd=repos["wt"])
    assert done.returncode == 0, done.stderr
    assert _git(repos["main"], "rev-parse", "HEAD") == head


def test_head_with_a_detached_main_checkout_is_refused(script_path: Path, repos: dict) -> None:
    _commit(repos["wt"], "a.txt", "a")
    _git(repos["main"], "switch", "-q", "--detach")
    done = _run(script_path, repos, "HEAD", "--worktree", str(repos["wt"]))
    assert done.returncode == 1
    assert "detached" in done.stderr and "branch" in done.stderr
    assert repos["wt"].exists()


def test_a_missing_target_branch_is_a_usage_error(script_path: Path, repos: dict) -> None:
    done = _run(script_path, repos, "--worktree", str(repos["wt"]))
    assert done.returncode != 0
    assert "target" in done.stderr
