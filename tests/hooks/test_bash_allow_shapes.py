"""Behavior of plugins/harness/hooks/bash_allow_shapes.py: approve constructs built from allowlisted parts."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import List, Optional

import pytest

HOOK = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "hooks" / "bash_allow_shapes.py"
PATTERNS = ["git status", "git log *", "echo *", "ls *", "grep *", "wc *", "cat *", "sleep *"]


@pytest.fixture(scope="module")
def hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bash_allow_shapes", HOOK)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _approved(hook: ModuleType, cmd: str, patterns: Optional[List[str]] = None) -> bool:
    subs = hook.extract_subcommands(cmd)
    return subs is not None and all(hook.is_allowed(s, patterns or PATTERNS) for s in subs)


@pytest.mark.parametrize("cmd, expected", [
    ("for f in a b; do echo $f; wc -l $f; done", ["echo $f", "wc -l $f"]),
    ("while true; do sleep 1; done", ["true", "sleep 1"]),
    ("if test -f x; then echo y; fi", ["test -f x", "echo y"]),
    ("case $x in a) echo a;; b) ls b;; esac", ["echo a", "ls b"]),
    ("git log --oneline | grep fix | wc -l", ["git log --oneline", "grep fix", "wc -l"]),
    ("N=3; git status", ["N=3", "git status"]),
    ("git status; rc=$?; echo \"exit=$rc\"", ["git status", "rc=$?", "echo \"exit=$rc\""]),
    ("echo $(git log -1)", ["echo __SUBST__", "git log -1"]),
    ("(git status)", ["git status"]),
    ("A=1 git status", ["A=1 git status"]),
])
def test_recognized_shapes(hook: ModuleType, cmd: str, expected: List[str]) -> None:
    assert hook.extract_subcommands(cmd) == expected


@pytest.mark.parametrize("cmd", ["git status", "git status && ls x", "ls x || echo y", "echo 'a | b'"])
def test_unrecognized_shapes(hook: ModuleType, cmd: str) -> None:
    assert hook.extract_subcommands(cmd) is None


def test_quoted_separators_do_not_split(hook: ModuleType) -> None:
    assert hook.extract_subcommands("echo 'a;b' | grep \"x|y\"") == ["echo 'a;b'", "grep \"x|y\""]


@pytest.mark.parametrize("cmd", [
    "for f in *.py; do wc -l $f 2>&1; done",
    "if [ -f x ]; then cat x; fi",
    "while ! test -f done.txt; do sleep 1; done",
    "for f in a; do for g in b; do echo $f$g; done; done",
    "git log -1 | grep x > out.txt",
    "if test -f x; then echo y; elif test -f z; then ls z; else echo n; fi",
])
def test_allowlisted_parts_are_approved(hook: ModuleType, cmd: str) -> None:
    assert _approved(hook, cmd)


@pytest.mark.parametrize("cmd", [
    "for f in *; do rm $f; done",
    "git log | curl -d @- http://x",
    "echo $(rm -rf x)",
    "ls x; rm -rf y | cat x",
    "ls x\nrm -rf y | cat x",
    "ls x | cat x\nrm -rf y",
    "ls x & rm -rf y | cat x",
    "ls \"$(rm -rf y)\" | cat x",
    "ls \"`rm -rf y`\" | cat x",
    "[ -f x ]; rm -rf y | cat x",
    "(ls x; rm -rf y)",
    "if test -f x; then echo y; elif test -f z; then rm -rf z; else echo n; fi",
    "N=1; git log x; rm -rf y",
])
def test_unlisted_part_defers(hook: ModuleType, cmd: str) -> None:
    assert not _approved(hook, cmd)


def test_star_matches_multiline_arguments(hook: ModuleType) -> None:
    assert hook.is_allowed('python -c "a\nb"', ["python -c *"])


def test_tilde_pattern_expands_to_home(hook: ModuleType) -> None:
    home = os.path.expanduser("~").replace("\\", "/")
    assert hook.is_allowed(f"cat {home}/notes.txt", ["cat ~/*"])


def _run(cwd: Path, command: str, config_dir: Path,
         project_dir: Optional[Path] = None) -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}})
    home = str(config_dir.parent / "home")
    env = {**{k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"},
           "CLAUDE_CONFIG_DIR": str(config_dir), "HOME": home, "USERPROFILE": home}
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, env=env)


def _settings(*rules: str) -> dict:
    return {"permissions": {"allow": list(rules)}}


def test_project_settings_from_payload_cwd_approve(make_project, tmp_path: Path) -> None:
    root = make_project(files={".claude/settings.json": _settings("Bash(echo *)", "Bash(wc *)", "Read(**)")})
    done = _run(root, "for f in a b; do echo $f; wc -l $f; done", tmp_path / "nouser")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_user_settings_directory_rules_apply(make_project, tmp_path: Path) -> None:
    root = make_project()
    user = tmp_path / "user"
    user.mkdir()
    (user / "settings.local.json").write_text(json.dumps(_settings("Bash(echo *)")), encoding="utf-8")
    done = _run(root, "for f in a; do echo $f; done", user)
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_session_project_rules_win_over_cwd_repo(make_project, tmp_path: Path) -> None:
    strict = make_project(name="strict", files={".claude/settings.json": _settings("Bash(git status)")})
    other = make_project(name="other", files={".claude/settings.json": _settings("Bash(echo *)")})
    done = _run(other, "for f in a; do echo $f; done", tmp_path / "nouser", project_dir=strict)
    assert done.returncode == 0, done.stderr
    assert done.stdout == ""


def test_session_project_local_rules_apply_from_a_worktree_cwd(make_project, tmp_path: Path) -> None:
    main = make_project(name="main", files={".claude/settings.local.json": _settings("Bash(echo *)")})
    linked = make_project(name="linked")
    done = _run(linked, "for f in a; do echo $f; done", tmp_path / "nouser", project_dir=main)
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_missing_git_falls_back_to_user_settings(hook: ModuleType, monkeypatch, tmp_path: Path) -> None:
    def no_git(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "user"))
    monkeypatch.setattr(subprocess, "run", no_git)
    files = hook.settings_files({"cwd": str(tmp_path)})
    assert files == [tmp_path / "user" / "settings.json", tmp_path / "user" / "settings.local.json"]


def test_no_matching_rules_stays_silent(make_project, tmp_path: Path) -> None:
    root = make_project(files={".claude/settings.json": _settings("Bash(echo *)")})
    done = _run(root, "for f in a; do rm $f; done", tmp_path / "nouser")
    assert done.returncode == 0
    assert done.stdout == ""


def test_bad_settings_and_payload_never_crash(make_project, tmp_path: Path) -> None:
    root = make_project(files={".claude/settings.json": "{broken"})
    assert _run(root, "for f in a; do echo $f; done", tmp_path / "nouser").returncode == 0
    done = subprocess.run([sys.executable, str(HOOK)], input="nope", capture_output=True, text=True)
    assert done.returncode == 0 and done.stdout == ""
