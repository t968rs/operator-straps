"""The writing-comments section command ``skills/writing-comments/commands/comment_sections.py``.

Each test runs the command as a subprocess against files in a ``make_project`` repo and reads its stdout,
stderr and exit code. The divider width comes from the project's ``comments.divider_width``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from conftest import PLUGIN_ROOT

COMMAND = PLUGIN_ROOT / "skills" / "writing-comments" / "commands" / "comment_sections.py"

RULE_88 = "# " + "-" * 86
SOURCE = (
    f"{RULE_88}\n"
    "# Ranking\n"
    f"{RULE_88}\n"
    "\n"
    "# -- row helpers " + "-" * 71 + "\n"
    "def f():\n"
    "    return 1\n"
    "\n"
    "### ======= CLASSES ======= ###\n"
)


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key != "CLAUDE_PROJECT_DIR"}
    return subprocess.run([sys.executable, str(COMMAND), *args], cwd=cwd, capture_output=True, text=True,
                          env=env, timeout=60)


def test_prints_the_outline_and_flags_of_a_file(make_project) -> None:
    root = make_project(files={"src/mod.py": SOURCE})
    done = _run(root, "src/mod.py")
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [
        "src/mod.py:1: major Ranking",
        "src/mod.py:5: minor row helpers",
        "src/mod.py:9: flag style: ### ======= CLASSES ======= ###",
    ]


def test_each_file_is_reported_in_the_order_named(make_project) -> None:
    root = make_project(files={"src/mod.py": SOURCE, "src/a.py": "x = 1\n"})
    done = _run(root, "src/a.py", "src/mod.py")
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines()[:2] == ["src/a.py: no dividers", "src/mod.py:1: major Ranking"]


def test_the_width_comes_from_the_project_key(make_project) -> None:
    rule_60 = "# " + "-" * 58
    root = make_project({"comments": {"divider_width": 60}},
                        files={"src/narrow.py": f"{rule_60}\n# Narrow\n{rule_60}\n"})
    done = _run(root, "src/narrow.py")
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["src/narrow.py:1: major Narrow"]


def test_an_absolute_path_is_reported_relative_to_the_project(make_project) -> None:
    root = make_project(files={"src/a.py": "x = 1\n"})
    done = _run(root, str(root / "src" / "a.py"))
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["src/a.py: no dividers"]


def test_a_missing_file_is_a_problem_line_and_prints_nothing(make_project) -> None:
    root = make_project(files={"src/a.py": "x = 1\n"})
    done = _run(root, "src/a.py", "src/gone.py")
    assert done.returncode == 1
    assert done.stdout == ""
    assert done.stderr.startswith("problem: ")
    assert "src/gone.py" in done.stderr


def test_a_non_python_file_is_a_problem_line(make_project) -> None:
    root = make_project(files={"notes.md": "# Notes\n"})
    done = _run(root, "notes.md")
    assert done.returncode == 1
    assert done.stdout == ""
    assert "notes.md" in done.stderr


def test_unparsable_source_is_a_problem_line(make_project) -> None:
    root = make_project(files={"src/bad.py": 'x = """never closed\n'})
    done = _run(root, "src/bad.py")
    assert done.returncode == 1
    assert done.stdout == ""
    assert "src/bad.py" in done.stderr


def test_no_path_is_a_problem_line(make_project) -> None:
    root = make_project()
    done = _run(root)
    assert done.returncode == 1
    assert done.stdout == ""
    assert done.stderr.startswith("problem: ")
