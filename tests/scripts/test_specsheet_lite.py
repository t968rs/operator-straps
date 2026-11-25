"""The spec sheet driver: ``specsheet_lite.py check <path>`` validates a sheet and names the next step."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from conftest import GIT_ENV, PLUGIN_ROOT
from harness_lib.specsheet_lite_models import TARGET_LINES, SpecSheet, render_sheet

SCRIPT = PLUGIN_ROOT / "scripts" / "specsheet_lite.py"
REL = "docs/SPECS/2026-11-25-brief.md"


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_ENV}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def _page(goals: int = 2) -> str:
    sheet = SpecSheet(title="Brief", day=date(2026, 11, 25), request="A short brief.",
                      goals=[f"Goal {n} holds." for n in range(goals)], avoid=["No second design document."])
    return render_sheet(sheet)


def test_check_passes_a_clean_sheet_and_names_write_plan(make_project) -> None:
    root = make_project(config={}, files={REL: _page()})
    done = _run(root, "check", REL)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0].startswith(f"check [ok] | {REL} | ")
    assert "2 goals" in lines[0] and "1 avoid" in lines[0]
    assert f'next: /harness:write-plan "Brief" --spec {REL}' in lines


def test_check_warns_past_the_target_length(make_project) -> None:
    root = make_project(config={}, files={REL: _page(goals=TARGET_LINES)})
    done = _run(root, "check", REL)
    assert done.returncode == 0, done.stderr
    assert any(line.startswith("warn: ") and str(TARGET_LINES) in line for line in done.stdout.splitlines())


def test_check_refuses_a_sheet_with_an_id(make_project) -> None:
    root = make_project(config={}, files={REL: _page().replace("Goal 1 holds.", "TASK-2 holds.")})
    done = _run(root, "check", REL)
    assert done.returncode == 1
    assert done.stderr.startswith("problem: ")


def test_check_refuses_a_page_out_of_shape(make_project) -> None:
    root = make_project(config={}, files={REL: _page().replace("## Request", "## Context")})
    done = _run(root, "check", REL)
    assert done.returncode == 1
    assert "problem: " in done.stderr


def test_check_refuses_a_missing_sheet(make_project) -> None:
    done = _run(make_project(config={}), "check", "docs/SPECS/nope.md")
    assert done.returncode == 1
    assert "problem: " in done.stderr and "nope.md" in done.stderr
