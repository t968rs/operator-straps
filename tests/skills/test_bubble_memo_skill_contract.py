"""The ``bubble-memo`` skill: argument tail, scripted commands, the dispatch rules and the loop."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _skill_parts import skill_parts  # noqa: E402

_LAUNCH = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/bubble_memo.py"'
_POINTER = "${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md"


@pytest.fixture()
def parts(repo_root: Path) -> Tuple[dict, str]:
    path = repo_root / "plugins" / "harness" / "skills" / "bubble-memo" / "SKILL.md"
    assert path.is_file(), f"{path} does not exist"
    return skill_parts(path)


def _fenced(body: str) -> List[str]:
    inside, lines = False, []
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
        elif inside:
            lines.append(line)
    return lines


def test_frontmatter_and_guidance_tail(parts: Tuple[dict, str]) -> None:
    front, _ = parts
    assert front["name"] == "bubble-memo"
    assert "-- <" in front["argument-hint"]
    assert front["description"].startswith("Use when")


def test_split_rule_cited_no_raw_arguments(parts: Tuple[dict, str]) -> None:
    _, body = parts
    assert _POINTER in body
    assert not [line for line in _fenced(body) if "$ARGUMENTS" in line]


def test_every_driver_command_goes_through_the_launcher(parts: Tuple[dict, str]) -> None:
    _, body = parts
    commands = [line.strip() for line in _fenced(body) if "bubble_memo.py" in line]
    assert commands, "the skill runs no bubble_memo.py command"
    assert all(line.startswith(_LAUNCH) for line in commands), commands


def test_the_loop_runs_the_driver_commands_in_order(parts: Tuple[dict, str]) -> None:
    _, body = parts
    tails = [line.split("bubble_memo.py", 1)[1].lstrip('"').split()
             for line in _fenced(body) if "bubble_memo.py" in line]
    verbs = [tail[0] for tail in tails if tail]
    assert verbs.index("scaffold") < verbs.index("apply") < verbs.index("check")


def test_agents_are_dispatched_by_the_printed_rows(parts: Tuple[dict, str]) -> None:
    _, body = parts
    for needle in ("harness:bubble-memo-investigator", "harness:bubble-memo-reviewer", "harness:parallel2",
                   "model", "one message", "Developer guidance:"):
        assert needle in body, needle


def test_the_skill_keeps_prose_and_the_snapshot_rule(parts: Tuple[dict, str]) -> None:
    _, body = parts
    assert "Description" in body and "Recommendation" in body
    assert "TODO(fill)" in body
