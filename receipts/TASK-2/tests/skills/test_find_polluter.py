"""Behavioral tests for the strap-debugging bisection script ``find-polluter.sh``.

Each test lays out test files in a scratch directory and runs the script with bash, using the current
interpreter as the test command so no JavaScript toolchain is needed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

BASH = shutil.which("bash")
pytestmark = [pytest.mark.cross_os, pytest.mark.skipif(BASH is None, reason="bash not on PATH")]

POLLUTE_IF_SPACED = "import pathlib, sys; ' ' in sys.argv[1] and pathlib.Path('.polluted').write_text('x')"


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> Path:
    return plugin_root / "skills" / "strap-debugging" / "find-polluter.sh"


def _layout(tmp_path: Path, names: List[str]) -> Path:
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    return tmp_path


def _run(script: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    # MSYS bash (Git for Windows) globs its argv when a Windows process starts it; the pattern must arrive
    # as typed, the way a shell user's quoted argument does.
    env = {**os.environ, "MSYS": "noglob"}
    return subprocess.run([BASH, script.as_posix(), *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60, env=env)


def _python() -> List[str]:
    return [Path(sys.executable).as_posix(), "-c", POLLUTE_IF_SPACED]


def test_finds_the_polluter_whose_path_has_a_space(script: Path, tmp_path: Path) -> None:
    root = _layout(tmp_path, ["t/a_test.py", "t/b c_test.py"])
    done = _run(script, root, ".polluted", "t/*_test.py", *_python())
    assert done.returncode == 1, done.stdout + done.stderr
    assert "FOUND POLLUTER" in done.stdout
    assert "Test: ./t/b c_test.py" in done.stdout


def test_clean_run_reports_no_polluter(script: Path, tmp_path: Path) -> None:
    root = _layout(tmp_path, ["t/a_test.py", "t/b_test.py"])
    done = _run(script, root, ".polluted", "t/*_test.py", *_python())
    assert done.returncode == 0, done.stdout + done.stderr
    assert "No polluter found" in done.stdout
    assert "Found 2 test files" in done.stdout


def test_missing_test_command_stops_instead_of_reporting_clean(script: Path, tmp_path: Path) -> None:
    root = _layout(tmp_path, ["t/a_test.py"])
    done = _run(script, root, ".polluted", "t/*_test.py", "no-such-test-runner-xyz")
    assert done.returncode == 2, done.stdout + done.stderr
    assert "No polluter found" not in done.stdout
    assert "no-such-test-runner-xyz" in done.stdout + done.stderr


def test_existing_target_stops_before_any_test_runs(script: Path, tmp_path: Path) -> None:
    root = _layout(tmp_path, ["t/a_test.py", "t/b c_test.py", ".polluted"])
    done = _run(script, root, ".polluted", "t/*_test.py", *_python())
    assert done.returncode == 2, done.stdout + done.stderr
    assert "already exists" in done.stdout
    assert "No polluter found" not in done.stdout
    assert "Testing:" not in done.stdout


def test_usage_without_arguments(script: Path, tmp_path: Path) -> None:
    done = _run(script, tmp_path)
    assert done.returncode == 2
    assert "Usage:" in done.stdout


@pytest.mark.parametrize("pattern", ["t/**/*_test.py", "./t/**/*_test.py"])
def test_double_star_pattern_also_matches_the_top_level(script: Path, tmp_path: Path, pattern: str) -> None:
    root = _layout(tmp_path, ["t/top_test.py", "t/sub/b c_test.py"])
    done = _run(script, root, ".polluted", pattern, *_python())
    assert done.returncode == 1, done.stdout + done.stderr
    assert "Found 2 test files" in done.stdout
    assert "Test: ./t/sub/b c_test.py" in done.stdout


def test_leading_dot_slash_pattern_is_stripped(script: Path, tmp_path: Path) -> None:
    root = _layout(tmp_path, ["t/a_test.py", "t/b_test.py"])
    done = _run(script, root, ".polluted", "./t/*_test.py", *_python())
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Found 2 test files" in done.stdout


def test_pattern_matching_nothing_stops_instead_of_reporting_clean(script: Path, tmp_path: Path) -> None:
    root = _layout(tmp_path, ["t/a_test.py"])
    done = _run(script, root, ".polluted", "nope/*_test.py", *_python())
    assert done.returncode == 2, done.stdout + done.stderr
    assert "No test files match" in done.stdout
    assert "No polluter found" not in done.stdout
