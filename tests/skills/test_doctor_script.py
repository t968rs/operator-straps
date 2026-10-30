"""Behavioral tests for the harness doctor skill command ``commands/doctor.py``.

Each case runs the command as a subprocess from a throwaway project, the way ``hpy`` launches it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

import pytest

from conftest import PLUGIN_ROOT

pytestmark = pytest.mark.cross_os

_SCRIPT = PLUGIN_ROOT / "skills" / "doctor" / "commands" / "doctor.py"


def _run(repo: Path, extra_env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **(extra_env or {})}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run([sys.executable, str(_SCRIPT), "--repo", str(repo)], capture_output=True, text=True,
                          env=env, timeout=120)


def test_healthy_project_exits_zero_with_the_status_line_first(make_project) -> None:
    done = _run(make_project({"base_branch": "main"}))
    assert done.returncode == 0, done.stdout + done.stderr
    first = done.stdout.splitlines()[0]
    assert first.startswith("doctor [")
    assert "[fail]" not in done.stdout


def test_broken_config_exits_one_and_names_the_file(make_project) -> None:
    done = _run(make_project(None, files={".claude/harness.json": "{not json"}))
    assert done.returncode == 1
    assert done.stdout.splitlines()[0].startswith("doctor [fail]")
    assert "[fail] config" in done.stdout


def test_unusable_interpreter_override_is_reported(make_project, tmp_path: Path) -> None:
    done = _run(make_project({}), {"HARNESS_PY": str(tmp_path / "no" / "python.exe")})
    assert "[warn] interpreter" in done.stdout
    assert "HARNESS_PY" in done.stdout


def test_command_lists_every_check_once(make_project) -> None:
    done = _run(make_project({}))
    names = [line.split(":")[0].split("] ")[1] for line in done.stdout.splitlines()[1:]
              if line.startswith("[")]
    assert names == ["python", "interpreter", "modules", "git", "gh", "repository", "config", "worktree_root"]
