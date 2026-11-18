"""tools/ci_local.py: the local replay of ci.yml's windows-latest leg stays in step with the workflow."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterator

import pytest

from conftest import REPO_ROOT

_SCRIPT = REPO_ROOT / "tools" / "ci_local.py"
_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def ci() -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location("ci_local_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(scope="module")
def workflow() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def test_replay_matches_the_workflow(ci: ModuleType, workflow: str) -> None:
    assert ci.workflow_drift(workflow) == []


HPY_STEP = "      - name: hpy launches under sh\n"
DRIFTS = [
    ('python-version: "3.11"', 'python-version: "3.12"', "setup-python version"),
    ("args=(-m cross_os)", 'args=(-m "cross_os or slow")', "pytest command"),
    ('--base "origin/$BASE_REF"', '--base "$BASE_REF"', "select command"),
    ("runner.os == 'Linux'", "runner.os != 'macOS'", "ruff is Linux-only"),
    ('import jsonschema, referencing, pydantic, sys', 'import jsonschema, sys', "hpy check"),
    ("os: [ubuntu-latest, windows-latest]", "os: [ubuntu-latest]", "windows-latest in the matrix"),
    ("tools/ci_test_runtime_catalog.py .artifacts", "tools/catalog.py .artifacts", "catalog command"),
    ("python -m pip install -r requirements-dev.txt", "uv pip install --system -r requirements-dev.txt",
     "python job step order"),
    (HPY_STEP, "      - name: lint docs\n        run: true\n" + HPY_STEP,
     "python job step order"),
    ("python tools/select_tests.py --full", "python tools/select_tests.py --all", "select command"),
    ("--junitxml=.artifacts/pytest-junit.xml", "--junitxml=.artifacts/junit.xml", "pytest command"),
    ('"$rc" = 5', '"$rc" = 4', "pytest command"),
    ("\n  python:\n", "\n  python-tests:\n", "python job step order"),
]


@pytest.mark.parametrize(("old", "new", "check"), DRIFTS, ids=[d[2] + f"-{i}" for i, d in enumerate(DRIFTS)])
def test_each_drift_names_its_check(ci: ModuleType, workflow: str, old: str, new: str, check: str) -> None:
    assert old in workflow
    assert check in ci.workflow_drift(workflow.replace(old, new, 1))


def test_pytest_argv_follows_the_workflow_order(ci: ModuleType, tmp_path: Path) -> None:
    junit = tmp_path / "out" / "pytest-junit.xml"
    argv = ci.pytest_argv(Path("py.exe"), ["tests/a/test_x.py", "tests/b/test_y.py"], junit)
    assert argv[1:] == ["-m", "pytest", "tests/a/test_x.py", "tests/b/test_y.py", "-m", "cross_os", "-q",
                        f"--junitxml={junit.as_posix()}"]


def test_shown_cuts_a_long_test_list_to_its_ends(ci: ModuleType) -> None:
    argv = ["py", "-m", "pytest", *[f"tests/t/test_{i}.py" for i in range(30)], "-m", "cross_os", "-q"]
    line = ci.shown(argv)
    assert line.startswith("py -m pytest tests/t/test_0.py tests/t/test_1.py ... (26 more")
    assert line.endswith("tests/t/test_29.py -m cross_os -q")
    assert ci.shown(["sh", "hpy", "-c", "x y"]) == "sh hpy -c 'x y'"


@pytest.mark.parametrize(("rc", "expected"), [(0, 0), (1, 1), (2, 2), (5, 0)])
def test_exit_five_is_a_pass_on_windows(ci: ModuleType, rc: int, expected: int) -> None:
    assert ci.windows_rc(rc) == expected


def test_ci_env_drops_session_variables_and_marks_the_runner(ci: ModuleType, tmp_path: Path) -> None:
    bash = tmp_path / "git" / "usr" / "bin"
    py = tmp_path / "py311"
    for folder in (bash, py, py / "Scripts"):
        folder.mkdir(parents=True)
    base = {"CLAUDE_PROJECT_DIR": "x", "HARNESS_PY": "x", "GIT_AUTHOR_NAME": "x", "PYTHONPATH": "x",
            "VIRTUAL_ENV": "x", "GITHUB_OUTPUT": "x", "RUNNER_TEMP": "x", "CONDA_PREFIX": "x",
            "APPDATA": "a", "TEMP": "t", "PATH": "old"}
    env = ci.ci_env(base, py / "python.exe", [bash], tmp_path / "gitconfig")
    for gone in ("CLAUDE_PROJECT_DIR", "HARNESS_PY", "GIT_AUTHOR_NAME", "PYTHONPATH", "VIRTUAL_ENV",
                 "GITHUB_OUTPUT", "RUNNER_TEMP", "CONDA_PREFIX"):
        assert gone not in env
    assert env["TEMP"] == "t"
    assert env["APPDATA"] == "a"
    assert (env["CI"], env["GITHUB_ACTIONS"], env["RUNNER_OS"]) == ("true", "true", "Windows")
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["MSYSTEM"] == "MINGW64"
    assert env["GIT_CONFIG_GLOBAL"] == str(tmp_path / "gitconfig")
    parts = env["PATH"].split(ci.os.pathsep)
    assert parts[:3] == [str(bash), str(py), str(py / "Scripts")]
    assert parts[-1] == "old"


def test_short_temp_replaces_both_temp_variables(ci: ModuleType) -> None:
    env = ci.with_temp({"TEMP": "a", "TMP": "b", "PATH": "p"}, "C:/RUNNER~1/Temp")
    assert (env["TEMP"], env["TMP"], env["PATH"]) == ("C:/RUNNER~1/Temp", "C:/RUNNER~1/Temp", "p")


def test_read_outputs_parses_github_output(ci: ModuleType) -> None:
    keys = ci.read_outputs("pytest=subset\nruff=none\nplugins=false\n")
    assert keys == {"pytest": "subset", "ruff": "none", "plugins": "false"}


def test_skip_reasons_counts_each_message(ci: ModuleType, tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite>'
        '<testcase name="a"><skipped message="no sh" /></testcase>'
        '<testcase name="b"><skipped message="no sh" /></testcase>'
        '<testcase name="c"><skipped message="symlinks need privilege" /></testcase>'
        '<testcase name="d" />'
        '</testsuite></testsuites>', encoding="utf-8")
    assert ci.skip_reasons(junit) == {"no sh": 2, "symlinks need privilege": 1}


def test_dirty_warnings_name_what_ci_cannot_see(ci: ModuleType) -> None:
    lines = ci.dirty_warnings(" M tools/x.py\n?? notes.txt\n", "tests/lib/test_new.py\n")
    assert any("2 uncommitted" in line for line in lines)
    assert any("tests/lib/test_new.py" in line for line in lines)
    assert ci.dirty_warnings("", "") == []


def test_version_gate_accepts_only_311(ci: ModuleType) -> None:
    assert ci.version_problem("3.11.9 (main)", any_python=False) is None
    assert "3.12.10" in ci.version_problem("3.12.10 (main)", any_python=False)
    assert ci.version_problem("3.12.10 (main)", any_python=True) is None


@pytest.mark.cross_os
@pytest.mark.skipif(sys.platform != "win32", reason="Git for Windows layout")
def test_git_bash_dirs_hold_sh(ci: ModuleType) -> None:
    dirs = ci.git_bash_dirs()
    found = {name: ci.shutil.which(name) for name in ("git", "bash", "sh")}
    assert any((d / "sh.exe").is_file() for d in dirs), f"no sh.exe in {dirs}; PATH resolves {found}"


def test_fresh_out_dir_refuses_a_folder_it_did_not_write(ci: ModuleType, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("mine", encoding="utf-8")
    problem = ci.fresh_out_dir(out)
    assert problem is not None and "holds files this tool did not write" in problem
    assert (out / "keep.txt").read_text(encoding="utf-8") == "mine"
    assert not (out / ci.OUT_MARKER).exists()


def test_fresh_out_dir_empties_a_marked_folder(ci: ModuleType, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / ci.OUT_MARKER).write_text("old", encoding="utf-8")
    (out / "stale.txt").write_text("x", encoding="utf-8")
    assert ci.fresh_out_dir(out) is None
    assert not (out / "stale.txt").exists()
    assert (out / ci.OUT_MARKER).read_text(encoding="utf-8") == "written by tools/ci_local.py\n"


@pytest.mark.parametrize("make", [False, True], ids=["missing", "empty"])
def test_fresh_out_dir_accepts_a_missing_or_empty_folder(ci: ModuleType, tmp_path: Path, make: bool) -> None:
    out = tmp_path / "a" / "out"
    if make:
        out.mkdir(parents=True)
    assert ci.fresh_out_dir(out) is None
    assert (out / ci.OUT_MARKER).is_file()


def test_safe_directories_round_trip_through_git(ci: ModuleType, tmp_path: Path) -> None:
    entries = ["E:\\work\\a#b;c", 'C:\\x "q"\\repo', "/srv/plain"]
    path = ci.write_safe_directories(tmp_path / "gitconfig", [*entries, "  "])
    done = subprocess.run(["git", "config", "--file", str(path), "--get-all", "safe.directory"],
                          capture_output=True, text=True, check=True)
    assert done.stdout.splitlines() == entries


def test_safe_directories_without_entries_leave_an_empty_file(ci: ModuleType, tmp_path: Path) -> None:
    path = ci.write_safe_directories(tmp_path / "gitconfig", [])
    assert path.read_text(encoding="utf-8") == ""
