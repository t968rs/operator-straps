"""Behavior of plugins/harness/scripts/hpy, the interpreter launcher every hook and skill command uses."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SH = shutil.which("sh")
pytestmark = pytest.mark.skipif(SH is None, reason="no POSIX sh on PATH")


def _run(plugin_root: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    hpy = (plugin_root / "scripts" / "hpy").as_posix()
    base = {k: v for k, v in os.environ.items() if k not in {"HARNESS_PY", "CLAUDE_PLUGIN_OPTION_PYTHON"}}
    return subprocess.run([SH, hpy, *args], capture_output=True, text=True, env={**base, **env})


def _posix(p: str) -> str:
    return Path(p).as_posix()


def test_harness_py_wins(plugin_root: Path) -> None:
    done = _run(
        plugin_root, {"HARNESS_PY": _posix(sys.executable)}, "-c", "import sys; print(sys.executable)"
    )
    assert done.returncode == 0, done.stderr
    assert Path(done.stdout.strip()).resolve() == Path(sys.executable).resolve()


def test_broken_candidate_is_skipped(plugin_root: Path, tmp_path: Path) -> None:
    env = {
        "HARNESS_PY": _posix(str(tmp_path / "missing.exe")),
        "CLAUDE_PLUGIN_OPTION_PYTHON": _posix(sys.executable),
    }
    done = _run(plugin_root, env, "-c", "import sys; print(sys.executable)")
    assert done.returncode == 0, done.stderr
    assert Path(done.stdout.strip()).resolve() == Path(sys.executable).resolve()


def test_interpreter_path_with_spaces_launches(plugin_root: Path, tmp_path: Path) -> None:
    shim = tmp_path / "Python Builds" / "python"
    shim.parent.mkdir()
    shim.write_text(f'#!/bin/sh\nexec "{_posix(sys.executable)}" "$@"\n', encoding="utf-8", newline="\n")
    shim.chmod(0o755)
    done = _run(plugin_root, {"HARNESS_PY": _posix(str(shim))}, "-c", "raise SystemExit(5)")
    assert done.returncode == 5, done.stderr


def test_py_launcher_fallback_passes_its_flag(plugin_root: Path, tmp_path: Path) -> None:
    shims = tmp_path / "shims"
    shims.mkdir()
    py = shims / "py"
    real = _posix(sys.executable)
    script = f'#!/bin/sh\n[ "$1" = -3 ] || exit 9\nshift\nexec "{real}" "$@"\n'
    py.write_text(script, encoding="utf-8", newline="\n")
    py.chmod(0o755)
    path = os.pathsep.join([str(shims), str(Path(SH).parent)])
    if shutil.which("python", path=str(Path(SH).parent)):
        pytest.skip("a python on the sh directory would win before the py fallback")
    done = _run(plugin_root, {"PATH": path}, "-c", "raise SystemExit(5)")
    assert done.returncode == 5, done.stderr


def test_arguments_and_exit_code_pass_through(plugin_root: Path) -> None:
    done = _run(
        plugin_root,
        {"HARNESS_PY": _posix(sys.executable)},
        "-c",
        "import sys; sys.exit(int(sys.argv[1]))",
        "7",
    )
    assert done.returncode == 7


def test_no_dependency_warning_with_full_interpreter(plugin_root: Path) -> None:
    pytest.importorskip("jsonschema")
    pytest.importorskip("pydantic")
    done = _run(plugin_root, {"HARNESS_PY": _posix(sys.executable)}, "-c", "pass")
    assert "WARNING" not in done.stderr
