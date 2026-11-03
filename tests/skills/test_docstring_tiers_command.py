"""The writing-docstrings tier command ``skills/writing-docstrings/commands/docstring_tiers.py``.

Each test runs the command as a subprocess against a file in a ``make_project`` repo and reads its stdout,
stderr and exit code.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List

from conftest import PLUGIN_ROOT

COMMAND = PLUGIN_ROOT / "skills" / "writing-docstrings" / "commands" / "docstring_tiers.py"

SOURCE = '''class Store:
    def get(self, key):
        """Get."""
        if key is None:
            raise KeyError(key)
        return self._data[key]


def load(path):
    """Returns the text of the file at ``path`` in full, read as UTF-8 for every caller."""
    return open(path).read()
'''


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key != "CLAUDE_PROJECT_DIR"}
    return subprocess.run([sys.executable, str(COMMAND), *args], cwd=cwd, capture_output=True, text=True,
                          env=env, timeout=60)


def _rows(done: subprocess.CompletedProcess) -> List[str]:
    return done.stdout.splitlines()


def test_prints_one_row_per_function(make_project) -> None:
    root = make_project(files={"src/store.py": SOURCE})
    done = _run(root, "src/store.py")
    assert done.returncode == 0, done.stderr
    rows = _rows(done)
    assert len(rows) == 2
    assert "Store.get lines=3 forks=2 suggest=2-compact current=placeholder?" in rows[0]
    assert "load lines=1 forks=0 suggest=1-brief current=brief" in rows[1]


def test_symbols_filter_by_name_or_qualname(make_project) -> None:
    root = make_project(files={"src/store.py": SOURCE})
    by_name = _rows(_run(root, "src/store.py", "get"))
    by_qualname = _rows(_run(root, "src/store.py", "Store.get"))
    assert len(by_name) == 1 and " Store.get " in by_name[0]
    assert by_qualname == by_name


def test_unknown_symbol_is_a_problem(make_project) -> None:
    root = make_project(files={"src/store.py": SOURCE})
    done = _run(root, "src/store.py", "put")
    assert done.returncode == 1
    assert "problem: no function named put in src/store.py" in done.stderr


def test_missing_file_is_a_problem(make_project) -> None:
    done = _run(make_project(), "src/nope.py")
    assert done.returncode == 1
    assert done.stderr.startswith("problem: ")
    assert "src/nope.py" in done.stderr


def test_syntax_error_is_a_problem(make_project) -> None:
    root = make_project(files={"src/bad.py": "def f(:\n    pass\n"})
    done = _run(root, "src/bad.py")
    assert done.returncode == 1
    assert done.stderr.startswith("problem: ")
    assert "Traceback" not in done.stderr


def test_line_length_comes_from_config(make_project) -> None:
    files = {"src/store.py": SOURCE}
    default = _rows(_run(make_project(files=files), "src/store.py", "load"))
    narrow = make_project({"docstrings": {"line_length": 60}}, files=files, name="narrow")
    flagged = _rows(_run(narrow, "src/store.py", "load"))
    assert len(default) == 1 and len(flagged) == 1
    assert "long-lines" not in default[0]
    assert "long-lines=[10]" in flagged[0]


def test_a_file_outside_the_cwd_reads_its_own_project(make_project, tmp_path: Path) -> None:
    narrow = make_project({"docstrings": {"line_length": 60}}, files={"src/store.py": SOURCE}, name="far")
    done = _run(tmp_path, str(narrow / "src" / "store.py"), "load")
    assert done.returncode == 0, done.stderr
    assert "long-lines=[10]" in done.stdout
