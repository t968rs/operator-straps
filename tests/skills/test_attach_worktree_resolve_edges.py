"""Edge cases of a-w resolution inside the worktree, found in review.

Each test builds a throwaway repository under ``tmp_path``: ``main`` has branch ``feature`` checked out and
``wt`` is a detached worktree cut from its one commit, the way ``d-w`` cuts one. The ``lagging`` fixture
instead cuts ``wt`` from a branch ``other`` that ``feature`` never merged.
"""
from __future__ import annotations

import os
import stat
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


def _state_file(wt: Path) -> Path:
    return Path(_git(wt, "rev-parse", "--path-format=absolute", "--git-path", "harness-attach.json"))


def _refusing_pre_rebase_hook(main: Path) -> Path:
    hooks = Path(_git(main, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-rebase"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hook


def _conflict(repos: dict) -> tuple:
    """A worktree commit and a target commit (plus a target-only file) that conflict on ``shared.txt``."""
    original = _commit(repos["wt"], "shared.txt", _WT, "worktree edit")
    _write(repos["main"], "other.txt", "other\n")
    moved = _commit(repos["main"], "shared.txt", _TARGET, "target edit")
    return original, moved


def _untouched(main: Path, head: str) -> None:
    assert _git(main, "status", "--porcelain") == ""
    assert _git(main, "rev-parse", "HEAD") == head


def test_a_rebase_that_never_starts_restores_the_worktree_and_refuses(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    original, moved = _conflict(repos)
    _refusing_pre_rebase_hook(main)
    done = _run(script_path, repos, "feature")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "nothing moved" in done.stderr and "--continue" not in done.stderr
    assert _git(wt, "rev-parse", "HEAD") == original
    assert not _state_file(wt).exists()
    _untouched(main, moved)


def test_continue_after_the_agent_aborted_the_rebase_refuses_and_lands_nothing(script_path: Path,
                                                                               repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _, moved = _conflict(repos)
    assert _run(script_path, repos, "feature").returncode == 2
    _git(wt, "rebase", "--abort")
    _commit(wt, "shared.txt", _RESOLVED, "resolved by hand")
    done = _run(script_path, repos, "--continue")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "--abort" in done.stderr
    assert _state_file(wt).is_file()
    _untouched(main, moved)


def test_a_restart_whose_rebase_never_starts_restores_the_worktree(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    original, _ = _conflict(repos)
    assert _run(script_path, repos, "feature").returncode == 2
    _write(wt, "shared.txt", _RESOLVED)
    _git(wt, "add", "shared.txt")
    late = _commit(main, "shared.txt", "one\nLATE\nthree\n", "late target edit")
    assert _run(script_path, repos, "--continue").returncode == 1
    _refusing_pre_rebase_hook(main)
    done = _run(script_path, repos, "--continue")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "nothing moved" in done.stderr and "--continue" not in done.stderr
    assert _git(wt, "rev-parse", "HEAD") == original
    assert not _state_file(wt).exists()
    _untouched(main, late)


def test_a_usage_error_exits_1_not_the_resolution_code(script_path: Path, repos: dict) -> None:
    done = _run(script_path, repos, "feature", "--auto-resolve", "nope")
    assert done.returncode == 1
    assert "usage" in done.stderr.lower()


def test_a_resolution_that_keeps_the_branch_copy_clears_the_state(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _, moved = _conflict(repos)
    assert _run(script_path, repos, "feature").returncode == 2
    _write(wt, "shared.txt", _TARGET)
    _git(wt, "add", "shared.txt")
    done = _run(script_path, repos, "--continue")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "branch's copy" in done.stderr and "--continue" not in done.stderr
    assert not _state_file(wt).exists()
    assert wt.exists()
    _untouched(main, moved)


def test_committed_refuses_a_merge_commit_it_would_have_to_rebase(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _git(wt, "switch", "-q", "-c", "side")
    _commit(wt, "side.txt", "side\n", "side work")
    _git(wt, "switch", "-q", "--detach", repos["base"])
    _commit(wt, "a.txt", "a\n", "mainline work")
    _git(wt, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    merged = _git(wt, "rev-parse", "HEAD")
    moved = _commit(main, "other.txt", "other\n", "target edit")
    done = _run(script_path, repos, "feature", "--committed")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "merge" in done.stderr and merged[:7] in done.stderr
    assert _git(wt, "rev-parse", "HEAD") == merged
    assert not _state_file(wt).exists()
    _untouched(main, moved)


def test_abort_ignores_auto_resolve_flags(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    original, moved = _conflict(repos)
    assert _run(script_path, repos, "feature").returncode == 2
    done = _run(script_path, repos, "--abort", "--auto-resolve", "shared.txt=worktree")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _git(wt, "rev-parse", "HEAD") == original
    assert not _state_file(wt).exists()
    _untouched(main, moved)


def test_a_restart_that_cannot_start_names_the_discarded_resolution(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _conflict(repos)
    assert _run(script_path, repos, "feature").returncode == 2
    _write(wt, "shared.txt", _RESOLVED)
    _git(wt, "add", "shared.txt")
    _commit(main, "shared.txt", "one\nLATE\nthree\n", "late target edit")
    assert _run(script_path, repos, "--continue").returncode == 1
    resolved = _git(wt, "rev-parse", "HEAD")
    _refusing_pre_rebase_hook(main)
    done = _run(script_path, repos, "--continue")
    assert done.returncode == 1, done.stdout + done.stderr
    assert f"reset --hard {resolved}" in done.stderr, done.stderr


def test_a_reset_during_the_stop_refuses_and_lands_nothing(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    original, moved = _conflict(repos)
    assert _run(script_path, repos, "feature").returncode == 2
    _git(wt, "reset", "-q", "--hard", original)
    done = _run(script_path, repos, "--continue")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "--abort" in done.stderr
    assert _state_file(wt).is_file()
    _untouched(main, moved)


def _break_editor(index: int) -> str:
    """A ``GIT_SEQUENCE_EDITOR`` that inserts a ``break`` line at ``index`` of the todo file, without sed."""
    code = ("import sys;from pathlib import Path as P;f=P(sys.argv[1]);"
            "l=f.read_bytes().decode().splitlines(True);"
            f"l.insert({index},'break'+chr(10));f.write_bytes(''.join(l).encode())")
    return f'"{Path(sys.executable).as_posix()}" -c "{code}"'


def _rebasing(wt: Path) -> bool:
    return any(Path(_git(wt, "rev-parse", "--path-format=absolute", "--git-path", name)).exists()
               for name in ("rebase-merge", "rebase-apply"))


def test_a_rebase_already_in_progress_refuses_before_the_attach_rebases(script_path: Path,
                                                                        repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _commit(wt, "shared.txt", _WT, "worktree edit")
    _commit(wt, "z.txt", "z\n", "worktree z")
    env = {**os.environ, **_GIT_ENV, "GIT_SEQUENCE_EDITOR": _break_editor(0)}
    subprocess.run(["git", "-C", str(wt), "rebase", "-i", "HEAD~1"], check=True, capture_output=True, env=env)
    assert _rebasing(wt)
    paused = _git(wt, "rev-parse", "HEAD")
    moved = _commit(main, "shared.txt", _TARGET, "target edit")
    done = _run(script_path, repos, "feature")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "rebase" in done.stderr and wt.resolve().as_posix() in done.stderr
    assert _rebasing(wt) and _git(wt, "rev-parse", "HEAD") == paused
    assert not _state_file(wt).exists()
    _untouched(main, moved)


@pytest.fixture()
def lagging(tmp_path: Path) -> dict:
    """``feature`` at the base; ``other`` adds ``f.txt`` and edits ``y.txt``; ``wt`` cut from ``other``."""
    main, wt = tmp_path / "main", tmp_path / "wt"
    _git(tmp_path, "init", "-q", "-b", "feature", str(main))
    base = _commit(main, "y.txt", "one\ntwo\nthree\n", "base")
    _git(main, "switch", "-q", "-c", "other")
    _write(main, "f.txt", "other-branch only\n")
    _commit(main, "y.txt", "one\nF\nthree\n", "other edit")
    _git(main, "switch", "-q", "feature")
    _git(main, "worktree", "add", "--quiet", "--detach", str(wt), "other")
    _commit(wt, "y.txt", "one\nWT\nthree\n", "worktree edit")
    return {"main": main, "wt": wt, "base": base}


@pytest.mark.parametrize("mode", [(), ("--committed",)])
def test_a_rebase_aborted_by_hand_from_a_foreign_cut_refuses(script_path: Path, lagging: dict,
                                                             mode: tuple) -> None:
    main, wt = lagging["main"], lagging["wt"]
    assert _run(script_path, lagging, "feature", *mode).returncode == 2
    _git(wt, "rebase", "--abort")
    _commit(wt, "y.txt", "one\nRESOLVED\nthree\n", "resolved by hand")
    done = _run(script_path, lagging, "--continue")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "--abort" in done.stderr
    assert _state_file(wt).is_file()
    _untouched(main, lagging["base"])
    assert not (main / "f.txt").exists()


def test_a_restart_keeps_the_original_cut_so_a_hand_merge_at_round_two_refuses(script_path: Path,
                                                                                lagging: dict) -> None:
    main, wt = lagging["main"], lagging["wt"]
    original = _git(wt, "rev-parse", "HEAD")
    _commit(main, "z.txt", "z\n", "target edit before the attach")
    assert _run(script_path, lagging, "feature").returncode == 2
    _write(wt, "y.txt", "one\nRESOLVED\nthree\n")
    _git(wt, "add", "y.txt")
    late = _commit(main, "y.txt", "one\nLATE\nthree\n", "late conflicting target edit")
    assert _run(script_path, lagging, "--continue").returncode == 1
    assert _run(script_path, lagging, "--continue").returncode == 2
    _git(wt, "rebase", "--abort")
    _git(wt, "reset", "-q", "--hard", original)
    subprocess.run(["git", "-C", str(wt), "merge", "--no-edit", "feature"], capture_output=True,
                   env={**os.environ, **_GIT_ENV})
    _write(wt, "y.txt", "one\nRESOLVED2\nthree\n")
    _git(wt, "add", "y.txt")
    _git(wt, "commit", "-q", "--no-edit")
    done = _run(script_path, lagging, "--continue")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "--abort" in done.stderr
    assert _state_file(wt).is_file()
    _untouched(main, late)
    assert not (main / "f.txt").exists()


@pytest.mark.parametrize("mode", [(), ("--committed",)])
def test_a_rebase_in_progress_without_a_conflict_refuses_before_anything_moves(script_path: Path,
                                                                                repos: dict,
                                                                                mode: tuple) -> None:
    main, wt = repos["main"], repos["wt"]
    _commit(wt, "a.txt", "a\n", "first worktree commit")
    _commit(wt, "b.txt", "b\n", "second worktree commit")
    env = {**os.environ, **_GIT_ENV, "GIT_SEQUENCE_EDITOR": _break_editor(1)}
    subprocess.run(["git", "-C", str(wt), "rebase", "-i", "HEAD~2"], check=True, capture_output=True, env=env)
    assert _rebasing(wt)
    paused = _git(wt, "rev-parse", "HEAD")
    done = _run(script_path, repos, "feature", *mode)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "rebase" in done.stderr and wt.resolve().as_posix() in done.stderr
    assert _rebasing(wt) and _git(wt, "rev-parse", "HEAD") == paused
    assert not _state_file(wt).exists()
    _untouched(main, repos["base"])
