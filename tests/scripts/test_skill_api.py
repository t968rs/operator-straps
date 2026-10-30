"""Behavioral tests of the plugin's generic ``scripts/skill_api.py`` launcher (D19).

``skill_api.py [--repo DIR] <module> [<name>]`` activates the project's configuration, imports
``harness_lib.<module>``, binds the names in its ``__all__`` (refusing a module without one), binds ``name``
when given and execs stdin. Any exception is one ``problem: <ExceptionName>: <message>`` line on stderr with
exit 1.

The launcher runs in-process through ``main``; the binding tests use the real ``harness_lib.strap_api`` and
the ``__all__`` refusal uses ``harness_lib.project``, a module that defines no ``__all__``.
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable, List, Tuple

import pytest

Result = Tuple[int, str, str]
Launch = Callable[..., Result]
NAME = "demo-skill"


@pytest.fixture(scope="module")
def launcher(plugin_root: Path) -> ModuleType:
    """Import skill_api.py by absolute path; a missing script fails here as an AssertionError."""
    path = plugin_root / "scripts" / "skill_api.py"
    assert path.is_file(), f"{path} does not exist"
    spec = importlib.util.spec_from_file_location("skill_api_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def project(make_project) -> Path:
    """A committed throwaway consuming project."""
    return make_project({"base_branch": "main"})


@pytest.fixture()
def launch(launcher: ModuleType, project: Path, monkeypatch: pytest.MonkeyPatch,
           capsys: pytest.CaptureFixture) -> Launch:
    """``launch(code, *args)`` -> (exit code, stdout, stderr) of ``skill_api.py --repo <project> *args``."""
    def _run(code: str, *args: str) -> Result:
        monkeypatch.setattr(sys, "stdin", io.StringIO(code))
        status = launcher.main(["--repo", str(project), *args])
        captured = capsys.readouterr()
        return status, captured.out, captured.err
    return _run


def problems(result: Result) -> List[str]:
    """Assert exit 1 with at least one stderr line, every one a ``problem:`` line; return those lines."""
    code, _, err = result
    lines = [line for line in err.splitlines() if line.strip()]
    assert code == 1 and lines, err
    assert all(line.startswith("problem: ") for line in lines), err
    return lines


def test_binds_every_all_name(launch: Launch) -> None:
    module = importlib.import_module("harness_lib.strap_api")
    names = list(getattr(module, "__all__", []))
    assert names, "harness_lib.strap_api defines no __all__"
    code = "bound = [" + ", ".join(names) + "]\nprint('bound', len(bound))\n"
    status, out, err = launch(code, "strap_api")
    assert status == 0, err
    assert f"bound {len(names)}" in out


def test_binds_name_and_execs_stdin(launch: Launch) -> None:
    status, out, err = launch('print("bound:", name)\n', "strap_api", NAME)
    assert status == 0, err
    assert f"bound: {NAME}" in out


def test_record_run_unbound_is_name_error(launch: Launch) -> None:
    lines = problems(launch("record_run\n", "strap_api", NAME))
    assert any(line.startswith("problem: NameError: ") and "record_run" in line for line in lines), lines


def test_exception_becomes_problem_line(launch: Launch) -> None:
    lines = problems(launch('raise ValueError("boom")\n', "strap_api", NAME))
    assert "problem: ValueError: boom" in lines, lines


def test_refuses_module_without_all(launch: Launch) -> None:
    module = importlib.import_module("harness_lib.project")
    assert not hasattr(module, "__all__"), "harness_lib.project gained __all__; pick another module"
    lines = problems(launch('print("ran")\n', "project"))
    assert "problem: harness_lib.project has no __all__" in lines, lines


def test_refusal_does_not_exec_stdin(launch: Launch) -> None:
    status, out, _ = launch('print("ran")\n', "project")
    assert status == 1 and "ran" not in out


def test_activates_project_config(launch: Launch, project: Path) -> None:
    code = "from harness_lib.config import active\nprint('root=' + active().project_root.as_posix())\n"
    status, out, err = launch(code, "strap_api", NAME)
    assert status == 0, err
    roots = [line[len("root="):] for line in out.splitlines() if line.startswith("root=")]
    assert roots and Path(roots[0]).samefile(project), out
