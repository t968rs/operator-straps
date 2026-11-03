"""``skill_api.py --file`` and the ``bin/harness-skill-api`` shim that puts it on a project skill's PATH.

``--file`` loads an API module by path, with its folder appended to ``sys.path`` so a sibling models module
imports; exactly one of a module name and ``--file`` is accepted; a missing file is one ``problem:`` line.
The shim runs the launcher through ``hpy`` from its own location and is executable in the index.
"""
from __future__ import annotations

import importlib.util
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence

import pytest

from conftest import PLUGIN_ROOT, REPO_ROOT, git

API = '__all__ = ["greet"]\n\nfrom demo_models import WORD\n\n\ndef greet(who):\n    return f"{WORD} {who}"\n'
MODELS = 'WORD = "hello"\n'
API_REL = ".claude/skills/demo/scripts/demo_api.py"
FILES = {API_REL: API, ".claude/skills/demo/scripts/demo_models.py": MODELS}
SHIM = PLUGIN_ROOT / "bin" / "harness-skill-api"
SH = shutil.which("sh")


@pytest.fixture(autouse=True)
def _restore_import_state(monkeypatch: pytest.MonkeyPatch):
    """Undo the launcher's ``sys.path`` appends and the cached ``sys.modules`` entries after each test."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    modules = dict(sys.modules)
    yield
    sys.modules.clear()
    sys.modules.update(modules)


@pytest.fixture(scope="module")
def launcher() -> ModuleType:
    path = PLUGIN_ROOT / "scripts" / "skill_api.py"
    spec = importlib.util.spec_from_file_location("skill_api_file_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _code(launcher: ModuleType, argv: Sequence[str], code: str, monkeypatch: pytest.MonkeyPatch) -> int:
    """Exit code of ``main(argv)`` with ``code`` on stdin; an argparse exit returns its code."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(code))
    try:
        return launcher.main(list(argv))
    except SystemExit as exc:
        return int(exc.code or 0)


def test_file_binds_the_api_module_and_its_sibling(make_project, launcher: ModuleType,
                                                    monkeypatch: pytest.MonkeyPatch,
                                                    capsys: pytest.CaptureFixture) -> None:
    root = make_project(config={}, files=dict(FILES))
    argv = ["--repo", str(root), "--file", str(root / API_REL), "demo"]
    code = _code(launcher, argv, "print(greet(name))\n", monkeypatch)
    out, err = capsys.readouterr()
    assert code == 0, err
    assert out == "hello demo\n"


def test_file_heredoc_runs_in_the_repo_root(make_project, launcher: ModuleType,
                                           monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture) -> None:
    where = '__all__ = ["where"]\n\nimport os\n\n\ndef where():\n    return os.getcwd()\n'
    root = make_project(config={}, files={".claude/skills/demo/scripts/where_api.py": where})
    before = os.getcwd()
    argv = ["--repo", str(root), "--file", str(root / ".claude/skills/demo/scripts/where_api.py"), "demo"]
    code = _code(launcher, argv, "print(where())\n", monkeypatch)
    out, err = capsys.readouterr()
    assert code == 0, err
    assert Path(out.strip()).resolve() == Path(root).resolve()
    assert os.getcwd() == before


def test_module_and_file_together_are_refused(make_project, launcher: ModuleType,
                                              monkeypatch: pytest.MonkeyPatch,
                                              capsys: pytest.CaptureFixture) -> None:
    root = make_project(config={}, files=dict(FILES))
    argv = ["--repo", str(root), "--file", str(root / API_REL), "strap_api", "demo"]
    code = _code(launcher, argv, "", monkeypatch)
    err = capsys.readouterr().err
    assert code == 1 and err.startswith("problem: ") and "not both" in err, err


def test_missing_file_is_one_problem_line(make_project, launcher: ModuleType,
                                          monkeypatch: pytest.MonkeyPatch,
                                          capsys: pytest.CaptureFixture) -> None:
    root = make_project(config={})
    argv = ["--repo", str(root), "--file", str(root / "absent_api.py"), "demo"]
    code = _code(launcher, argv, "", monkeypatch)
    err = capsys.readouterr().err
    assert code == 1 and err.startswith("problem: ") and "absent_api.py" in err, err


def test_shim_is_executable_in_the_index() -> None:
    staged = git(REPO_ROOT, "ls-files", "-s", "--", "plugins/harness/bin/harness-skill-api")
    assert staged.startswith("100755 "), staged


@pytest.mark.cross_os
@pytest.mark.skipif(SH is None, reason="no POSIX sh on PATH")
def test_shim_runs_the_launcher(make_project) -> None:
    assert SHIM.is_file(), SHIM
    root = make_project(config={}, files=dict(FILES))
    env = {**os.environ, "HARNESS_PY": Path(sys.executable).as_posix()}
    done = subprocess.run([SH, SHIM.as_posix(), "--repo", str(root), "--file", str(root / API_REL), "demo"],
                          input="print(greet(name))\n", capture_output=True, text=True, env=env,
                          cwd=str(Path(root)))
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "hello demo"
