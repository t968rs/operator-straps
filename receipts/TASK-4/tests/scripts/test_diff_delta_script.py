"""Behavioral tests for the plugin's scripts/diff_delta.py: the delta between two git refs of a project.

Each test builds a throwaway project with ``make_project`` (an exclusions file naming ``gen/*``), adds a
second commit, and runs the script by path with the current interpreter and ``--repo``.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from conftest import PLUGIN_ROOT, git

_SCRIPT = PLUGIN_ROOT / "scripts" / "diff_delta.py"
_EXCLUSIONS = {"exclusions": [{"pattern": "gen/*", "reason": "generated report"}]}


def _project(make_project: Callable[..., Path]) -> Path:
    root = make_project(config={"exclusions": "config/ex.json"},
                        files={"config/ex.json": _EXCLUSIONS, "src/a.py": "x\n"})
    (root / "src" / "a.py").write_text("x\ny\nz\nw\n", encoding="utf-8")
    (root / "gen").mkdir()
    (root / "gen" / "out.json").write_text("".join(f"{n}\n" for n in range(10)), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "second")
    return root


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_SCRIPT), *args, "--repo", str(root)],
                          cwd=str(root), capture_output=True, text=True)


def test_prints_one_status_line(make_project: Callable[..., Path]) -> None:
    done = _run(_project(make_project), "HEAD~1", "HEAD")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == (
        "delta [ok] | source +3/-0 (net +3), 1 file | total +13/-0 (net +13), 2 files | excluded 1"
    )


def test_json_prints_the_payload(make_project: Callable[..., Path]) -> None:
    done = _run(_project(make_project), "HEAD~1", "HEAD", "--json")
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    counts = (payload["adds"], payload["subs"], payload["files"], payload["excluded"])
    assert counts == (3, 0, 1, ["gen/out.json"])
    assert payload["full"]["adds"] == 13


def test_bad_ref_exits_one_with_a_problem_line(make_project: Callable[..., Path]) -> None:
    done = _run(_project(make_project), "HEAD", "no-such-ref")
    assert done.returncode == 1
    assert done.stderr.startswith("problem: ")
    assert done.stdout == ""
