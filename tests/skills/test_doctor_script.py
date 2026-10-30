"""Behavioral tests for the harness doctor skill command ``commands/doctor.py``.

Each case runs the command as a subprocess from a throwaway project, the way ``hpy`` launches it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

import pytest

from conftest import PLUGIN_ROOT

pytestmark = pytest.mark.cross_os

_SCRIPT = PLUGIN_ROOT / "skills" / "doctor" / "commands" / "doctor.py"


def _run(repo: Path, config_dir: Path,
         extra_env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """Runs the command with user settings read from ``config_dir``, never the machine's own settings."""
    base = {key: value for key, value in os.environ.items()
            if key not in ("CLAUDE_PROJECT_DIR", "HARNESS_PY", "CLAUDE_PLUGIN_OPTION_PYTHON")}
    env = {**base, "CLAUDE_CONFIG_DIR": str(config_dir), **(extra_env or {})}
    return subprocess.run([sys.executable, str(_SCRIPT), "--repo", str(repo)], capture_output=True, text=True,
                          env=env, timeout=120)


def _empty_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


def test_healthy_project_exits_zero_with_the_status_line_first(make_project, tmp_path: Path) -> None:
    done = _run(make_project({"base_branch": "main"}), _empty_config_dir(tmp_path))
    assert done.returncode == 0, done.stdout + done.stderr
    first = done.stdout.splitlines()[0]
    assert first.startswith("doctor [")
    assert "[fail]" not in done.stdout


def test_broken_config_exits_one_and_names_the_file(make_project, tmp_path: Path) -> None:
    done = _run(make_project(None, files={".claude/harness.json": "{not json"}), _empty_config_dir(tmp_path))
    assert done.returncode == 1
    assert done.stdout.splitlines()[0].startswith("doctor [fail]")
    assert "[fail] config" in done.stdout


def test_unusable_interpreter_override_is_reported(make_project, tmp_path: Path) -> None:
    done = _run(make_project({}), _empty_config_dir(tmp_path),
                {"HARNESS_PY": str(tmp_path / "no" / "python.exe")})
    assert "[warn] interpreter" in done.stdout
    assert "HARNESS_PY" in done.stdout


def test_python_option_in_user_settings_is_reported_when_not_exported(make_project, tmp_path: Path) -> None:
    config_dir = _empty_config_dir(tmp_path)
    elsewhere = str(tmp_path / "envs" / "other" / "python.exe")
    settings = {"pluginConfigs": {"harness@some-marketplace": {"options": {"python": elsewhere}}}}
    (config_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    done = _run(make_project({}), config_dir)
    assert "[warn] interpreter" in done.stdout
    assert elsewhere in done.stdout


def test_command_lists_every_check_once(make_project, tmp_path: Path) -> None:
    done = _run(make_project({}), _empty_config_dir(tmp_path))
    names = [line.split(":")[0].split("] ")[1] for line in done.stdout.splitlines()[1:]
              if line.startswith("[")]
    assert names == ["python", "interpreter", "modules", "git", "gh", "repository", "config", "worktree_root"]
