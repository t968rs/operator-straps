"""Behavior of plugins/harness/hooks/approve_python_c.py: opt-in auto-approval of ``python -c`` one-liners."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

HOOKS = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "hooks"
HOOK = HOOKS / "approve_python_c.py"


def _run(cwd: Path, command: str, tool: str = "Bash") -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_name": tool, "cwd": str(cwd), "tool_input": {"command": command}})
    return subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True)


def _decision(done: subprocess.CompletedProcess) -> Optional[str]:
    assert done.returncode == 0, done.stderr
    if not done.stdout.strip():
        return None
    return json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"]


def test_shell_script_is_gone() -> None:
    assert not (HOOKS / "approve-python-c.sh").exists()


@pytest.mark.parametrize("command", [
    "python -c \"print(1)\"",
    "python3 -c 'import sys\n# comment\nprint(sys.version)'",
])
def test_opted_in_project_approves_python_c(make_project, command: str) -> None:
    root = make_project(config={"auto_approve_python_c": True})
    assert _decision(_run(root, command)) == "allow"


def test_subdirectory_cwd_resolves_the_project(make_project) -> None:
    root = make_project(config={"auto_approve_python_c": True}, files={"src/a.py": "x = 1\n"})
    assert _decision(_run(root / "src", "python -c \"print(1)\"")) == "allow"


def test_default_config_stays_silent(make_project) -> None:
    root = make_project()
    assert _decision(_run(root, "python -c \"print(1)\"")) is None


def test_explicit_false_stays_silent(make_project) -> None:
    root = make_project(config={"auto_approve_python_c": False})
    assert _decision(_run(root, "python -c \"print(1)\"")) is None


@pytest.mark.parametrize(
    "command", ["python script.py", "pythonx -c 1", "echo python -c 1", "python -m pytest"]
)
def test_other_commands_stay_silent(make_project, command: str) -> None:
    root = make_project(config={"auto_approve_python_c": True})
    assert _decision(_run(root, command)) is None


@pytest.mark.parametrize("command", [
    "python -c \"print(1)\"\nrm -rf target",
    "python -c 'print(1)'; rm -rf target",
    "python -c 'print(1)' && rm -rf target",
    "python -c 'print(1)' | sh",
    "python -c 'print(1)' > out.txt",
    "python -c \"$(rm -rf target)\"",
    "python -c \"`rm -rf target`\"",
    "python -c $(rm -rf target)",
    "python -c $'x\\' ; rm -rf target ; \\''",
    "python -c 'unterminated",
])
def test_trailing_or_embedded_commands_stay_silent(make_project, command: str) -> None:
    root = make_project(config={"auto_approve_python_c": True})
    assert _decision(_run(root, command)) is None


@pytest.mark.parametrize("command", [
    "python -c 'a = \"x; y | z\"\n# note\nprint(a)'",
    "python -c \"import sys; print(sys.argv)\" one two",
    "python -c \"print('a && b')\"",
])
def test_operators_inside_quotes_are_approved(make_project, command: str) -> None:
    root = make_project(config={"auto_approve_python_c": True})
    assert _decision(_run(root, command)) == "allow"


def test_other_tools_stay_silent(make_project) -> None:
    root = make_project(config={"auto_approve_python_c": True})
    assert _decision(_run(root, "python -c 1", tool="PowerShell")) is None


def test_invalid_config_stays_silent(make_project) -> None:
    root = make_project(files={".claude/harness.json": "{not json"})
    assert _decision(_run(root, "python -c 1")) is None


def test_unparseable_payload_stays_silent() -> None:
    done = subprocess.run([sys.executable, str(HOOK)], input="nope", capture_output=True, text=True)
    assert _decision(done) is None
