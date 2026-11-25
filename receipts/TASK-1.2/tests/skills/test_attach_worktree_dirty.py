"""Behavioral tests for a-w onto a dirty target: overlap check, trial merge, auto-resolve rules, backup, undo.

Each test builds a throwaway repository under ``tmp_path``: ``main`` has branch ``feature`` checked out and
``wt`` is a detached worktree cut from it the way ``d-w`` cuts one.
"""
from __future__ import annotations

import importlib.util
import json
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
_RUN0, _RUN1, _RUN2 = '{"run": 0}\n', '{"run": 1}\n', '{"run": 2}\n'


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **_GIT_ENV}
    done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env)
    return done.stdout.strip("\n")


def _write(repo: Path, name: str, text: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
    base = _commit(main, "report.json", _RUN0, "base")
    _git(main, "worktree", "add", "--quiet", "--detach", str(wt), base)
    return {"main": main, "wt": wt, "base": base}


def _attach(script_path: Path, repos: dict, *flags: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(script_path), "feature", "--worktree", str(repos["wt"]), *flags]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=repos["main"],
                          env={**os.environ, **_GIT_ENV})


def _staged(main: Path) -> list:
    return sorted(_git(main, "diff", "--cached", "--name-only").splitlines())


def _status(main: Path) -> list:
    return sorted(_git(main, "status", "--porcelain").splitlines())


def _read(repo: Path, name: str) -> str:
    return (repo / name).read_text(encoding="utf-8")


def test_a_dirty_path_the_move_does_not_write_stays_as_it_was(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _commit(wt, "a.txt", "a\n")
    _write(main, "shared.txt", "dirty\n")
    done = _attach(script_path, repos)
    assert done.returncode == 0, done.stderr
    assert _staged(main) == ["a.txt"]
    assert _read(main, "shared.txt") == "dirty\n"
    assert " M shared.txt" in _status(main)
    assert _git(main, "rev-parse", "HEAD") == repos["base"]
    assert not wt.exists()


def test_a_staged_dirty_edit_in_the_target_stays_staged(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _commit(wt, "a.txt", "a\n")
    _write(main, "shared.txt", "staged\n")
    _git(main, "add", "shared.txt")
    done = _attach(script_path, repos)
    assert done.returncode == 0, done.stderr
    assert _staged(main) == ["a.txt", "shared.txt"]
    assert _git(main, "show", ":shared.txt") == "staged"


def test_an_overlapping_dirty_path_refuses_naming_it_and_changes_nothing(script_path: Path,
                                                                        repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _write(wt, "shared.txt", "one\nWT\nthree\n")
    _write(main, "shared.txt", "dirty\n")
    before = _status(main)
    done = _attach(script_path, repos)
    assert done.returncode == 1
    assert "shared.txt" in done.stderr
    assert _status(main) == before
    assert _read(main, "shared.txt") == "dirty\n"
    assert _read(wt, "shared.txt") == "one\nWT\nthree\n"


def test_an_untracked_target_file_on_a_path_the_move_adds_refuses(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _write(wt, "new.txt", "theirs\n")
    _write(main, "new.txt", "mine\n")
    done = _attach(script_path, repos)
    assert done.returncode == 1
    assert "new.txt" in done.stderr and "untracked" in done.stderr
    assert _staged(main) == []
    assert _read(main, "new.txt") == "mine\n"
    assert wt.exists()


def test_an_unruled_conflict_with_uncommitted_worktree_changes_refuses_leaving_the_target_clean(
        script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _write(wt, "shared.txt", "one\nWT\nthree\n")
    moved = _commit(main, "shared.txt", "one\nTARGET\nthree\n", "target edit")
    done = _attach(script_path, repos)
    assert done.returncode == 1
    assert "shared.txt" in done.stderr and "commit" in done.stderr
    assert _status(main) == []
    assert _git(main, "rev-parse", "HEAD") == moved
    assert "<<<<<<<" not in _read(main, "shared.txt")
    assert _read(wt, "shared.txt") == "one\nWT\nthree\n"
    assert _git(wt, "diff", "--cached") == "", "the worktree's own index is untouched"


def test_a_conflict_ruled_for_the_worktree_lands_its_copy(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _write(wt, "report.json", _RUN2)
    _write(wt, "a.txt", "a\n")
    moved = _commit(main, "report.json", _RUN1, "target report")
    done = _attach(script_path, repos, "--auto-resolve", "report.json=worktree")
    assert done.returncode == 0, done.stderr
    assert _staged(main) == ["a.txt", "report.json"]
    assert _read(main, "report.json") == _RUN2
    assert _git(main, "rev-parse", "HEAD") == moved


def test_a_conflict_ruled_for_the_branch_keeps_the_target_copy(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _write(wt, "report.json", _RUN2)
    _write(wt, "a.txt", "a\n")
    _commit(main, "report.json", _RUN1, "target report")
    done = _attach(script_path, repos, "--auto-resolve", "report.json=branch")
    assert done.returncode == 0, done.stderr
    assert _staged(main) == ["a.txt"]
    assert _read(main, "report.json") == _RUN1


def test_project_config_rules_apply_without_flags(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _git(main, "worktree", "remove", "--force", str(wt))
    rules = {"attach": {"auto_resolve": [{"pattern": "*offlineTestReport.json", "in_favor_of": "worktree"}]}}
    _write(main, ".claude/harness.json", json.dumps(rules))
    cut = _commit(main, "out/offlineTestReport.json", "base\n", "config and report")
    _git(main, "worktree", "add", "--quiet", "--detach", str(wt), cut)
    _commit(wt, "out/offlineTestReport.json", "worktree\n", "worktree report")
    _commit(main, "out/offlineTestReport.json", "target\n", "target report")
    done = _attach(script_path, repos)
    assert done.returncode == 0, done.stderr
    assert _staged(main) == ["out/offlineTestReport.json"]
    assert _read(main, "out/offlineTestReport.json") == "worktree\n"


def test_rules_naming_different_sides_for_one_path_refuse_as_ambiguous(script_path: Path,
                                                                      repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _commit(wt, "report.json", _RUN2, "worktree report")
    moved = _commit(main, "report.json", _RUN1, "target report")
    done = _attach(script_path, repos, "--auto-resolve", "*.json=worktree",
                   "--auto-resolve", "report.json=branch")
    assert done.returncode == 1
    assert "report.json" in done.stderr and "ambiguous" in done.stderr
    assert _status(main) == []
    assert _git(main, "rev-parse", "HEAD") == moved
    assert wt.exists()


def test_a_dirty_overlap_ruled_for_the_branch_skips_the_path(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _write(wt, "report.json", _RUN2)
    _write(wt, "a.txt", "a\n")
    _write(main, "report.json", "dirty\n")
    done = _attach(script_path, repos, "--auto-resolve", "report.json=branch")
    assert done.returncode == 0, done.stderr
    assert _staged(main) == ["a.txt"]
    assert _read(main, "report.json") == "dirty\n"
    assert " M report.json" in _status(main)


def test_a_dirty_overlap_ruled_for_the_worktree_is_overwritten_and_the_printed_undo_restores_it(
        script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _write(wt, "report.json", _RUN2)
    _write(wt, "a.txt", "a\n")
    _write(main, "report.json", '{"run": "staged"}\n')
    _git(main, "add", "report.json")
    _write(main, "report.json", '{"run": "dirty"}\n')
    done = _attach(script_path, repos, "--auto-resolve", "report.json=worktree")
    assert done.returncode == 0, done.stderr
    assert _read(main, "report.json") == _RUN2
    assert _staged(main) == ["a.txt", "report.json"]
    assert "report.json" in done.stdout
    found = re.search(r"--source=([0-9a-f]{7,40}) --worktree", done.stdout)
    assert found, done.stdout
    backup = found.group(1)
    _git(main, "restore", f"--source={backup}^2", "--staged", "--", "report.json")
    _git(main, "restore", f"--source={backup}", "--worktree", "--", "report.json")
    assert _read(main, "report.json") == '{"run": "dirty"}\n'
    assert _git(main, "show", ":report.json") == '{"run": "staged"}'


def test_the_staged_report_names_the_backup_and_a_path_scoped_undo(script_path: Path, repos: dict) -> None:
    main, wt = repos["main"], repos["wt"]
    _commit(wt, "a.txt", "a\n")
    _write(main, "shared.txt", "dirty\n")
    done = _attach(script_path, repos)
    assert done.returncode == 0, done.stderr
    assert re.search(r"backup\b.*\b[0-9a-f]{7,40}\b", done.stdout), done.stdout
    assert "restore --source=HEAD --staged --worktree -- a.txt" in done.stdout


def _load_driver(script_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(script_path.parent))
    spec = importlib.util.spec_from_file_location("attach_worktree_under_test", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_git_older_than_2_40_is_refused_naming_the_requirement(script_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    driver = _load_driver(script_path, monkeypatch)
    with pytest.raises(driver.AttachError, match="2.40"):
        driver.check_git_version("git version 2.39.2")
    driver.check_git_version("git version 2.45.1.windows.1")
    driver.check_git_version("git version 3.0.0")
