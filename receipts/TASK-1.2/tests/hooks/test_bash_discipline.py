"""Behavior of plugins/harness/hooks/bash_discipline.py: one command per Bash call."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Optional

import pytest

HOOK = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "hooks" / "bash_discipline.py"
OPTION = "CLAUDE_PLUGIN_OPTION_BASH_DISCIPLINE"


@pytest.fixture(scope="module")
def hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bash_discipline", HOOK)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(
    command: str, option: Optional[str] = None, raw: Optional[str] = None
) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != OPTION}
    if option is not None:
        env[OPTION] = option
    payload = (
        raw if raw is not None else json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    )
    return subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, env=env)


def _decision(done: subprocess.CompletedProcess) -> Optional[str]:
    if not done.stdout.strip():
        return None
    return json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"]


@pytest.mark.parametrize("cmd", [
    "git status && git log",
    "cd /x ; git status",
    "echo a; echo b",
    "ls; for f in *; do echo $f; done",
])
def test_chains_are_violations(hook: ModuleType, cmd: str) -> None:
    assert hook.check_command(cmd) is not None


@pytest.mark.parametrize("cmd", [
    "git -C /repo status",
    'echo "a && b; c"',
    "echo 'x; y'",
    "echo a\\;b",
    "for f in *.py; do echo $f; wc -l $f; done",
    "while true; do sleep 1; done",
    "if test -f x; then echo y; elif test -f z; then echo z; else echo n; fi",
    "case $x in a) echo a;; b) echo b;; esac",
    "N=3; for i in 1 2; do echo $i; done",
    "A=1; B=2; if true; then echo ok; fi",
    'git commit -m "$(cat <<\'EOF\'\nsubject\n\nbody; with semicolon && amp\nEOF\n)"',
    "git commit -F - <<'EOF'\nsubject; more\nbody && rest\nEOF",
    "cat <<EOF > notes.txt\na; b\nEOF",
])
def test_allowed_shapes(hook: ModuleType, cmd: str) -> None:
    assert hook.check_command(cmd) is None


@pytest.mark.parametrize("cmd", [
    'echo "<<EOF"\ngit add . && git commit -m x\nEOF',
    "echo '<<EOF'\nls; pwd\nEOF",
    "cat <<<EOF\ngit add . && git commit -m x\nEOF",
    "cat <<EOF\n$(rm a; curl b)\nEOF",
    "cat <<EOF\n`rm a; curl b`\nEOF",
    "cat <<'EOF'\nbody\nEOF\nls && pwd",
])
def test_heredoc_lookalikes_still_deny(hook: ModuleType, cmd: str) -> None:
    assert hook.check_command(cmd) is not None


def test_leading_assignment_before_plain_command_is_still_a_chain(hook: ModuleType) -> None:
    assert hook.check_command("X=1; git status") is not None


def test_cd_chain_names_git_c(hook: ModuleType) -> None:
    assert "git -C" in hook.check_command("cd /repo; git status")


def test_violation_denies_through_hook_json() -> None:
    done = _run("git add . && git commit")
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    assert "&&" in out["permissionDecisionReason"]


def test_clean_command_is_silent() -> None:
    done = _run("git status")
    assert done.returncode == 0
    assert _decision(done) is None


@pytest.mark.parametrize("value", ["false", "0", "FALSE", " False "])
def test_option_off_disables_the_hook(value: str) -> None:
    done = _run("a && b", option=value)
    assert done.returncode == 0
    assert _decision(done) is None


@pytest.mark.parametrize("value", [None, "true", "1", "", "yes"])
def test_option_otherwise_enforces(value: Optional[str]) -> None:
    assert _decision(_run("a && b", option=value)) == "deny"


def test_unparseable_payload_never_blocks() -> None:
    done = _run("", raw="not json")
    assert done.returncode == 0
    assert done.stdout == ""
