"""The spec sheet driver: ``spec_it.py check <path>`` validates a sheet and names the next step."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from conftest import GIT_ENV, PLUGIN_ROOT
from harness_lib.spec_it_models import MAX_LINES, TARGET_LINES, SpecSheet, render_sheet

SCRIPT = PLUGIN_ROOT / "scripts" / "spec_it.py"
REL = "docs/SPECS/2026-11-25-brief.md"


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_ENV}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def _fields(goals: int) -> dict:
    return {"title": "Brief", "day": date(2026, 11, 25), "request": "A short brief.",
            "goals": [f"Goal {n} holds." for n in range(goals)], "avoid": ["No second design document."]}


def _page(goals: int = 2) -> str:
    return render_sheet(SpecSheet(**_fields(goals)))


def _goals_for(lines: int) -> int:
    """The goal count that brings ``_page`` to exactly ``lines`` lines."""
    return lines - len(_page(goals=1).splitlines()) + 1


def test_check_passes_a_clean_sheet_and_names_write_plan(make_project) -> None:
    root = make_project(config={}, files={REL: _page()})
    done = _run(root, "check", REL)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0].startswith(f"check [ok] | {REL} | ")
    assert "2 goals" in lines[0] and "1 avoid" in lines[0]
    assert f"| {len(_page().splitlines())} lines |" in lines[0]
    assert f'next: /harness:write-plan "Brief" --spec "{REL}"' in lines


def test_check_takes_an_absolute_sheet_path(make_project) -> None:
    root = make_project(config={}, files={REL: _page()})
    absolute = (root / REL).as_posix()
    done = _run(root, "check", absolute)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0].startswith(f"check [ok] | {absolute} | ")
    assert any(line.startswith('next: /harness:write-plan "Brief" --spec ') and REL in line for line in lines)


def test_check_warns_past_the_target_length(make_project) -> None:
    at_target = _page(goals=_goals_for(TARGET_LINES))
    past = _page(goals=_goals_for(TARGET_LINES + 1))
    assert len(at_target.splitlines()) == TARGET_LINES and len(past.splitlines()) == TARGET_LINES + 1
    root = make_project(config={}, files={REL: at_target, "docs/SPECS/2026-11-25-past.md": past})
    quiet = _run(root, "check", REL)
    assert quiet.returncode == 0, quiet.stderr
    assert not any(line.startswith("warn: ") for line in quiet.stdout.splitlines())
    done = _run(root, "check", "docs/SPECS/2026-11-25-past.md")
    assert done.returncode == 0, done.stderr
    assert any(line.startswith("warn: ") and str(TARGET_LINES) in line for line in done.stdout.splitlines())


def test_check_refuses_a_page_over_max_lines(make_project) -> None:
    over = render_sheet(SpecSheet.model_construct(**_fields(_goals_for(MAX_LINES + 1))))
    assert len(over.splitlines()) == MAX_LINES + 1
    done = _run(make_project(config={}, files={REL: over}), "check", REL)
    assert done.returncode == 1
    assert "problem: " in done.stderr and "line cap" in done.stderr


def test_check_refuses_a_sheet_with_an_id(make_project) -> None:
    root = make_project(config={}, files={REL: _page().replace("Goal 1 holds.", "TASK-2 holds.")})
    done = _run(root, "check", REL)
    assert done.returncode == 1
    assert done.stderr.startswith("problem: ")
    assert "a plan item id" in done.stderr


def test_check_refuses_a_page_out_of_shape(make_project) -> None:
    root = make_project(config={}, files={REL: _page().replace("## Request", "## Context")})
    done = _run(root, "check", REL)
    assert done.returncode == 1
    assert "problem: " in done.stderr


def test_check_refuses_a_missing_sheet(make_project) -> None:
    done = _run(make_project(config={}), "check", "docs/SPECS/nope.md")
    assert done.returncode == 1
    assert "problem: " in done.stderr and "nope.md" in done.stderr
