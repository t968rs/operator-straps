"""Behavioral tests for a-w resolution inside the worktree: exit 2, ``--continue``, ``--abort``, the race
refusal and the ``--committed`` rebase onto a target that moved.

Each test builds a throwaway repository under ``tmp_path``: ``main`` has branch ``feature`` checked out and
``wt`` is a detached worktree cut from it the way ``d-w`` cuts one.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

pytestmark = pytest.mark.cross_os

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t"}
_WT, _TARGET, _RESOLVED = "one\nWT\nthree\n", "one\nTARGET\nthree\n", "one\nRESOLVED\nthree\n"


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


def _attach(script_path: Path, repos: dict, *flags: str) -> subprocess.CompletedProcess:
    return _run(script_path, repos, "feature", *flags)


def _staged(main: Path) -> list:
    return sorted(_git(main, "diff", "--cached", "--name-only").splitlines())


def _state_file(wt: Path) -> Path:
    return Path(_git(wt, "rev-parse", "--path-format=absolute", "--git-path", "harness-attach.json"))


def _rebasing(wt: Path) -> bool:
    return any(Path(_git(wt, "rev-parse", "--path-format=absolute", "--git-path", name)).exists()
               for name in ("rebase-merge", "rebase-apply"))


def _stop_on_shared(script_path: Path, repos: dict, *flags: str) -> dict:
    """A worktree commit and a target commit that conflict on ``shared.txt``; the attach stops with exit 2."""
    original = _commit(repos["wt"], "shared.txt", _WT, "worktree edit")
    moved = _commit(repos["main"], "shared.txt", _TARGET, "target edit")
    done = _attach(script_path, repos, *flags)
    assert done.returncode == 2, done.stdout + done.stderr
    return {"original": original, "moved": moved, "done": done}


def _resolve(wt: Path) -> None:
    _write(wt, "shared.txt", _RESOLVED)
    _git(wt, "add", "shared.txt")


def test_an_unruled_conflict_stops_with_exit_2_and_leaves_the_target_clean(script_path: Path,
                                                                           repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    stop = _stop_on_shared(script_path, repos)
    output = stop["done"].stdout + stop["done"].stderr
    assert "shared.txt" in output and wt.resolve().as_posix() in output
    assert "--continue" in output and "--abort" in output
    assert _git(main, "status", "--porcelain") == ""
    assert _git(main, "rev-parse", "HEAD") == stop["moved"]
    assert "<<<<<<<" in (wt / "shared.txt").read_text(encoding="utf-8")
    assert _state_file(wt).is_file()


def test_continue_after_the_agent_resolves_stages_the_result(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    stop = _stop_on_shared(script_path, repos)
    _resolve(wt)
    done = _run(script_path, repos, "--continue")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (main / "shared.txt").read_text(encoding="utf-8") == _RESOLVED
    assert _staged(main) == ["shared.txt"]
    assert _git(main, "rev-parse", "HEAD") == stop["moved"]
    assert not wt.exists()


def test_staged_resolution_squashes_so_the_conflict_comes_up_once(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _commit(wt, "shared.txt", "one\nWT1\nthree\n", "first worktree edit")
    _commit(wt, "shared.txt", "one\nWT2\nthree\n", "second worktree edit")
    _commit(main, "shared.txt", _TARGET, "target edit")
    assert _attach(script_path, repos).returncode == 2
    _resolve(wt)
    done = _run(script_path, repos, "--continue")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (main / "shared.txt").read_text(encoding="utf-8") == _RESOLVED


def test_abort_returns_the_worktree_to_its_original_head_and_clears_the_state(script_path: Path,
                                                                             repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    stop = _stop_on_shared(script_path, repos)
    done = _run(script_path, repos, "--abort")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _git(wt, "rev-parse", "HEAD") == stop["original"]
    assert not _rebasing(wt)
    assert not _state_file(wt).exists()
    assert (wt / "shared.txt").read_text(encoding="utf-8") == _WT
    assert _git(main, "status", "--porcelain") == ""
    assert _git(main, "rev-parse", "HEAD") == stop["moved"]


def test_a_plain_rerun_while_stopped_refuses_naming_continue_and_abort(script_path: Path,
                                                                      repos: dict) -> None:
    _stop_on_shared(script_path, repos)
    done = _attach(script_path, repos)
    assert done.returncode == 1
    assert "--continue" in done.stderr and "--abort" in done.stderr
    assert _state_file(repos["wt"]).is_file()


def test_continue_with_a_different_mode_refuses(script_path: Path, repos: dict) -> None:
    _stop_on_shared(script_path, repos)
    _resolve(repos["wt"])
    done = _run(script_path, repos, "--continue", "--committed")
    assert done.returncode == 1
    assert _state_file(repos["wt"]).is_file()
    assert _git(repos["main"], "status", "--porcelain") == ""


def test_a_target_that_moves_during_resolution_refuses_then_continue_lands(script_path: Path,
                                                                          repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _stop_on_shared(script_path, repos)
    _resolve(wt)
    late = _commit(main, "other.txt", "other\n", "late target edit")
    raced = _run(script_path, repos, "--continue")
    assert raced.returncode == 1
    assert "--continue" in raced.stderr
    assert _git(main, "rev-parse", "HEAD") == late
    assert _git(main, "status", "--porcelain") == ""
    assert _state_file(wt).is_file()
    done = _run(script_path, repos, "--continue")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _staged(main) == ["shared.txt"]
    assert (main / "shared.txt").read_text(encoding="utf-8") == _RESOLVED
    assert (main / "other.txt").exists()
    assert _git(main, "rev-parse", "HEAD") == late


def test_committed_rebases_onto_a_moved_target_and_fast_forwards(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _commit(wt, "a.txt", "a\n", "first")
    _commit(wt, "b.txt", "b\n", "second")
    _commit(main, "other.txt", "other\n", "target edit")
    done = _attach(script_path, repos, "--committed")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _git(main, "log", "--format=%s", "-3").splitlines() == ["second", "first", "target edit"]
    assert _git(main, "status", "--porcelain") == ""
    assert (main / "other.txt").exists()
    assert not wt.exists()


def test_committed_conflict_stops_then_continue_fast_forwards_keeping_messages(script_path: Path,
                                                                              repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _stop_on_shared(script_path, repos, "--committed")
    _resolve(wt)
    done = _run(script_path, repos, "--continue")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _git(main, "log", "--format=%s", "-2").splitlines() == ["worktree edit", "target edit"]
    assert (main / "shared.txt").read_text(encoding="utf-8") == _RESOLVED
    assert _git(main, "status", "--porcelain") == ""


def test_committed_rule_settles_a_rebase_stop_on_its_own(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _commit(wt, "report.json", '{"run": 2}\n', "worktree report")
    _commit(main, "report.json", '{"run": 1}\n', "target report")
    done = _attach(script_path, repos, "--committed", "--auto-resolve", "report.json=worktree")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (main / "report.json").read_text(encoding="utf-8") == '{"run": 2}\n'
    assert _git(main, "log", "--format=%s", "-2").splitlines() == ["worktree report", "target report"]


def test_committed_with_a_dirty_overlap_refuses_even_under_a_rule(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _commit(wt, "report.json", '{"run": 2}\n', "worktree report")
    _write(main, "report.json", "dirty\n")
    done = _attach(script_path, repos, "--committed", "--auto-resolve", "report.json=branch")
    assert done.returncode == 1
    assert "report.json" in done.stderr
    assert (main / "report.json").read_text(encoding="utf-8") == "dirty\n"
    assert _git(main, "rev-parse", "HEAD") == repos["base"]
    assert wt.exists()


def test_committed_from_a_cut_the_target_lacks_carries_only_the_worktrees_commits(script_path: Path,
                                                                                 repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _git(main, "worktree", "remove", "--force", str(wt))
    _git(main, "switch", "-q", "-c", "other")
    foreign = _commit(main, "foreign.txt", "foreign\n", "foreign work")
    _git(main, "switch", "-q", "feature")
    _git(main, "worktree", "add", "--quiet", "--detach", str(wt), foreign)
    _commit(wt, "mine.txt", "mine\n", "mine work")
    done = _attach(script_path, repos, "--committed")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _git(main, "log", "--format=%s", "-2").splitlines() == ["mine work", "base"]
    assert not (main / "foreign.txt").exists()
    assert (main / "mine.txt").exists()


def test_the_module_docstring_names_the_new_interface(script_path: Path) -> None:
    doc = ast.get_docstring(ast.parse(script_path.read_text(encoding="utf-8")))
    for flag in ("--auto-resolve", "--continue", "--abort"):
        assert flag in doc, flag
    assert "no tracked changes" not in doc and "markers" not in doc
