"""Behavior of plugins/harness/hooks/powershell_allow_shapes.py: approve pipelines of allowlisted stages."""
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

HOOK = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "hooks" / "powershell_allow_shapes.py"


@pytest.fixture(scope="module")
def hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("powershell_allow_shapes", HOOK)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("cmd, stages", [
    ("Get-ChildItem | Select-Object -First 3", ["Get-ChildItem", "Select-Object -First 3"]),
    ("Write-Output 'a|b' | Out-Null", ["Write-Output 'a|b'", "Out-Null"]),
    ('Write-Output "x`"|y" | Out-String', ['Write-Output "x`"|y"', "Out-String"]),
    ("Get-Item a`|b", ["Get-Item a`|b"]),
    ("Write-Output 'a; b && c' | Out-Null", ["Write-Output 'a; b && c'", "Out-Null"]),
    ("Get-Item a`;b | Out-Null", ["Get-Item a`;b", "Out-Null"]),
])
def test_pipeline_split(hook: ModuleType, cmd: str, stages: list) -> None:
    assert hook._split_pipeline(cmd) == stages


@pytest.mark.parametrize("cmd", [
    "Get-ChildItem x; Remove-Item y | Out-Null",
    "Get-ChildItem x\nRemove-Item y | Out-Null",
    "Get-ChildItem x && Remove-Item y | Out-Null",
    "git status || Remove-Item y | Out-Host",
    "Get-ChildItem $(Remove-Item y) | Out-Null",
    "Get-ChildItem \"$(Remove-Item y)\" | Out-Null",
    "Get-ChildItem @(Remove-Item y) | Out-Null",
    "Get-ChildItem 'unterminated | Out-Null",
])
def test_statement_separators_and_subexpressions_refuse_the_split(hook: ModuleType, cmd: str) -> None:
    assert hook._split_pipeline(cmd) == []


@pytest.mark.parametrize("stage, allowed", [
    ("Out-Null", True),
    ("Format-Table -AutoSize", True),
    ("Get-ChildItem -Path x", True),
    ("& \"C:/tools/app.exe\" --version", True),
    ("Remove-Item x", False),
])
def test_stage_allowed(hook: ModuleType, stage: str, allowed: bool) -> None:
    patterns = ["Get-ChildItem *", "C:/tools/app.exe\" --version", "\"C:/tools/app.exe\" *"]
    assert hook._stage_allowed(stage, patterns) is allowed


def _run(cwd: Path, command: str, config_dir: Path, tool: str = "PowerShell",
         project_dir: Optional[Path] = None) -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_name": tool, "cwd": str(cwd), "tool_input": {"command": command}})
    home = str(config_dir.parent / "home")
    env = {**{k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"},
           "CLAUDE_CONFIG_DIR": str(config_dir), "HOME": home, "USERPROFILE": home}
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, env=env)


def _decision(done: subprocess.CompletedProcess) -> Optional[str]:
    assert done.returncode == 0, done.stderr
    return (
        json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] if done.stdout.strip() else None
    )


def _project(make_project) -> Path:
    allow = ["PowerShell(Get-ChildItem *)", "PowerShell(Select-Object *)", "Bash(ls *)"]
    rules = {"permissions": {"allow": allow}}
    return make_project(files={".claude/settings.json": rules})


def test_allowlisted_pipeline_is_approved(make_project, tmp_path: Path) -> None:
    done = _run(
        _project(make_project), "Get-ChildItem -Path x | Select-Object -First 1 | Out-Null", tmp_path / "u"
    )
    assert _decision(done) == "allow"


def test_user_settings_directory_rules_apply(make_project, tmp_path: Path) -> None:
    user = tmp_path / "user"
    user.mkdir()
    rules = {"permissions": {"allow": ["PowerShell(Get-Content *)"]}}
    (user / "settings.json").write_text(json.dumps(rules), encoding="utf-8")
    assert _decision(_run(make_project(), "Get-Content a.txt | Out-String", user)) == "allow"


def test_session_project_rules_win_over_cwd_repo(make_project, tmp_path: Path) -> None:
    strict = make_project(name="strict", files={".claude/settings.json": {"permissions": {"allow": []}}})
    done = _run(_project(make_project), "Get-ChildItem -Path x | Select-Object -First 1", tmp_path / "u",
                project_dir=strict)
    assert _decision(done) is None


def test_session_project_local_rules_apply_from_a_worktree_cwd(make_project, tmp_path: Path) -> None:
    rules = {"permissions": {"allow": ["PowerShell(Get-ChildItem *)"]}}
    main = make_project(name="main", files={".claude/settings.local.json": rules})
    done = _run(make_project(name="linked"), "Get-ChildItem x | Out-Null", tmp_path / "u", project_dir=main)
    assert _decision(done) == "allow"


@pytest.mark.parametrize("command", [
    "Get-ChildItem x | Remove-Item",
    "Get-ChildItem -Path x",
    "Get-ChildItem x; Remove-Item y | Out-Null",
])
def test_unlisted_stage_or_single_stage_defers(make_project, tmp_path: Path, command: str) -> None:
    assert _decision(_run(_project(make_project), command, tmp_path / "u")) is None


def test_other_tools_defer(make_project, tmp_path: Path) -> None:
    done = _run(_project(make_project), "Get-ChildItem x | Out-Null", tmp_path / "u", tool="Bash")
    assert _decision(done) is None


def test_unparseable_payload_never_crashes() -> None:
    done = subprocess.run([sys.executable, str(HOOK)], input="nope", capture_output=True, text=True)
    assert _decision(done) is None
