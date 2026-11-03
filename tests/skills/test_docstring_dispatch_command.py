"""The writing-docstrings dispatch command ``skills/writing-docstrings/commands/docstring_dispatch.py``.

Each test runs the command as a subprocess in a ``make_project`` repo and reads its stdout, stderr and exit
code. Rows are separated by one blank line.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

from conftest import PLUGIN_ROOT

COMMAND = PLUGIN_ROOT / "skills" / "writing-docstrings" / "commands" / "docstring_dispatch.py"
PROBE = "_docstring_probe.py"
WORK = "agent=harness:docstring-writer model=opus"
A = "def f():\n    return 1\n"
B = "def g():\n    return 2\n"


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key != "CLAUDE_PROJECT_DIR"}
    return subprocess.run([sys.executable, str(COMMAND), *args], cwd=cwd, capture_output=True, text=True,
                          env=env, timeout=60)


def _rows(done: subprocess.CompletedProcess) -> List[List[str]]:
    return [block.splitlines() for block in done.stdout.strip().split("\n\n")]


def _p(path: Path) -> str:
    return path.resolve().as_posix()


def _project(make_project) -> Path:
    return make_project(files={"src/a.py": A, "src/b.py": B, "pkg/c.py": A})


@pytest.mark.cross_os
def test_two_files_print_one_row(make_project) -> None:
    root = _project(make_project)
    done = _run(root, "src/a.py", "src/b.py")
    assert done.returncode == 0, done.stderr
    rows = _rows(done)
    assert len(rows) == 1
    assert rows[0][:3] == [WORK, f"Project root: {_p(root)}", "New docstrings: no"]
    assert [line for line in rows[0] if line.startswith("Scope: ")] == [
        f"Scope: {_p(root / 'src' / 'a.py')}: all",
        f"Scope: {_p(root / 'src' / 'b.py')}: all",
    ]
    assert not (root / "src" / PROBE).exists()


@pytest.mark.cross_os
def test_project_root_is_the_first_path_s_checkout(make_project) -> None:
    root = _project(make_project)
    from_subfolder = _run(root / "src", "a.py")
    from_outside = _run(root.parent, str(root / "src" / "a.py"))
    for done in (from_subfolder, from_outside):
        assert done.returncode == 0, done.stderr
        assert _rows(done)[0][1] == f"Project root: {_p(root)}"


def test_parallel_prints_the_probe_row_then_one_row_per_file(make_project) -> None:
    root = _project(make_project)
    done = _run(root, "-p", "src/a.py", "src/b.py")
    assert done.returncode == 0, done.stderr
    rows = _rows(done)
    assert len(rows) == 3
    assert rows[0][0] == "agent=harness:docstring-writer model=haiku" and rows[0][-1] == "Probe: yes"
    assert all(row[0] == WORK for row in rows[1:])
    assert (root / "src" / PROBE).is_file()


def test_parallel_over_two_folders_probes_each_folder(make_project) -> None:
    root = _project(make_project)
    done = _run(root, "-p", "src/a.py", "pkg/c.py")
    assert done.returncode == 0, done.stderr
    probe = _rows(done)[0]
    assert [line for line in probe if line.startswith("Scope: ")] == [
        f"Scope: {_p(root / 'pkg' / PROBE)}: all",
        f"Scope: {_p(root / 'src' / PROBE)}: all",
    ]
    assert (root / "pkg" / PROBE).is_file() and (root / "src" / PROBE).is_file()


def test_long_parallel_flag_matches_the_short_one(make_project) -> None:
    root = _project(make_project)
    long_flag = _run(root, "--parallel", "src/a.py", "src/b.py")
    assert long_flag.returncode == 0, long_flag.stderr
    assert long_flag.stdout == _run(root, "-p", "src/a.py", "src/b.py").stdout


def test_flags_between_paths_are_accepted(make_project) -> None:
    root = _project(make_project)
    done = _run(root, "src/a.py", "-p", "src/b.py", "-in")
    assert done.returncode == 0, done.stderr
    rows = _rows(done)
    assert len(rows) == 3 and all(row[2] == "New docstrings: yes" for row in rows)


def test_a_directory_and_a_file_in_it_give_one_row_per_file(make_project) -> None:
    root = _project(make_project)
    done = _run(root, "-p", "src", "src/a.py")
    assert done.returncode == 0, done.stderr
    work = [row for row in _rows(done) if row[0] == WORK]
    scopes = [line for row in work for line in row if line.startswith("Scope: ")]
    assert scopes == [f"Scope: {_p(root / 'src' / 'a.py')}: all", f"Scope: {_p(root / 'src' / 'b.py')}: all"]


def test_parallel_over_one_file_writes_no_probe(make_project) -> None:
    root = _project(make_project)
    done = _run(root, "-p", "src/a.py")
    assert done.returncode == 0, done.stderr
    assert len(_rows(done)) == 1
    assert not (root / "src" / PROBE).exists()


def test_include_new_flags_set_new_docstrings(make_project) -> None:
    root = _project(make_project)
    for flag in ("-in", "--include-new"):
        done = _run(root, flag, "src/a.py")
        assert done.returncode == 0, done.stderr
        assert _rows(done)[0][2] == "New docstrings: yes"


def test_a_problem_prints_nothing_on_stdout(make_project) -> None:
    root = _project(make_project)
    done = _run(root, "-p", "src/a.py::nope", "src/b.py")
    assert done.returncode == 1
    assert done.stdout == ""
    assert done.stderr.splitlines() and all(line.startswith("problem: ") for line in done.stderr.splitlines())
    assert not (root / "src" / PROBE).exists()


def test_unknown_flag_is_a_problem_line(make_project) -> None:
    root = _project(make_project)
    done = _run(root, "--bogus", "src/a.py")
    assert done.returncode == 1
    assert done.stderr.startswith("problem: ")


def test_no_path_is_a_problem_line(make_project) -> None:
    root = _project(make_project)
    done = _run(root)
    assert done.returncode == 1
    assert done.stderr.startswith("problem: ")


def test_clear_probe_removes_the_recorded_probes(make_project) -> None:
    root = _project(make_project)
    assert _run(root, "-p", "src/a.py", "pkg/c.py").returncode == 0
    done = _run(root, "--clear-probe")
    assert done.returncode == 0, done.stderr
    assert not (root / "src" / PROBE).exists() and not (root / "pkg" / PROBE).exists()
    assert _p(root / "src" / PROBE) in done.stdout


def test_clear_probe_leaves_an_unrecorded_probe_named_file(make_project) -> None:
    root = _project(make_project)
    assert _run(root, "-p", "src/a.py", "src/b.py").returncode == 0
    (root / "pkg" / PROBE).write_text("mine = 1\n", encoding="utf-8")
    done = _run(root, "--clear-probe")
    assert done.returncode == 0, done.stderr
    assert not (root / "src" / PROBE).exists()
    assert (root / "pkg" / PROBE).read_text(encoding="utf-8") == "mine = 1\n"


def test_clear_probe_with_a_path_is_a_problem_line(make_project) -> None:
    root = _project(make_project)
    assert _run(root, "-p", "src/a.py", "src/b.py").returncode == 0
    done = _run(root, "--clear-probe", "pkg")
    assert done.returncode == 1
    assert done.stdout == "" and done.stderr.startswith("problem: ")
    assert (root / "src" / PROBE).is_file()


def test_repo_flag_names_the_project(make_project) -> None:
    root = _project(make_project)
    done = _run(root.parent, "--repo", str(root), str(root / "src" / "a.py"))
    assert done.returncode == 0, done.stderr
    assert _rows(done)[0][1] == f"Project root: {_p(root)}"


def test_clear_probe_with_repo_clears_that_project(make_project) -> None:
    root = _project(make_project)
    assert _run(root, "-p", "src/a.py", "src/b.py").returncode == 0
    done = _run(root.parent, "--clear-probe", "--repo", str(root))
    assert done.returncode == 0, done.stderr
    assert not (root / "src" / PROBE).exists()
    assert _p(root / "src" / PROBE) in done.stdout


def test_an_invalid_config_is_a_problem_line(make_project) -> None:
    root = make_project(config={"no_such_key": 1}, files={"src/a.py": A})
    done = _run(root, "src/a.py")
    assert done.returncode == 1
    assert done.stdout == ""
    assert done.stderr.startswith("problem: ")


def test_a_later_run_removes_a_stale_probe_in_another_folder(make_project) -> None:
    root = _project(make_project)
    assert _run(root, "-p", "src/a.py", "src/b.py").returncode == 0
    done = _run(root, "pkg/c.py")
    assert done.returncode == 0, done.stderr
    assert not (root / "src" / PROBE).exists()
