"""Behavioral test for the checkout that supplies a-w's ``attach.auto_resolve`` rules.

The repository under ``tmp_path`` keeps an untracked ``.claude/harness.json`` in its main checkout ``main``;
the target branch ``feature`` is checked out in the linked worktree ``target`` (a collector worktree, say),
and ``wt`` is a detached worktree cut the way ``d-w`` cuts one. An untracked file never reaches a linked
worktree, so the rules have to come from the main checkout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

pytestmark = pytest.mark.cross_os

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t"}
_REPORT = "out/offlineTestReport.json"


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
    """``main`` with an untracked rule file; ``target`` on ``feature``; ``wt`` cut from the base."""
    main, target, wt = tmp_path / "main", tmp_path / "target", tmp_path / "wt"
    _git(tmp_path, "init", "-q", "-b", "main", str(main))
    base = _commit(main, _REPORT, "base\n", "base")
    rules = {"attach": {"auto_resolve": [{"pattern": "*offlineTestReport.json", "in_favor_of": "worktree"}]}}
    _write(main, ".claude/harness.json", json.dumps(rules))
    _git(main, "worktree", "add", "--quiet", "-b", "feature", str(target), base)
    _git(main, "worktree", "add", "--quiet", "--detach", str(wt), base)
    return {"main": main, "target": target, "wt": wt}


def test_untracked_main_checkout_rules_apply_to_a_target_in_a_linked_worktree(script_path: Path,
                                                                             repos: dict) -> None:
    target, wt = repos["target"], repos["wt"]
    _commit(wt, _REPORT, "worktree\n", "worktree report")
    moved = _commit(target, _REPORT, "target\n", "target report")
    assert not (target / ".claude" / "harness.json").exists()
    cmd = [sys.executable, str(script_path), "feature", "--worktree", str(wt)]
    done = subprocess.run(cmd, capture_output=True, text=True, cwd=target, env={**os.environ, **_GIT_ENV})
    assert done.returncode == 0, done.stdout + done.stderr
    assert _git(target, "diff", "--cached", "--name-only").splitlines() == [_REPORT]
    assert (target / _REPORT).read_text(encoding="utf-8") == "worktree\n"
    assert _git(target, "rev-parse", "HEAD") == moved
