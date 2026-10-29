"""Guard test: every user-invocable harness skill takes the ``-- <guidance>`` tail of the shared reference.

The hint advertises the tail, the body points at ``reference/skill_arguments.md`` for the split rule, and no
fenced command carries ``$ARGUMENTS``: the raw text would reach the shell with the guidance attached.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _skill_parts import skill_parts  # noqa: E402

_PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_SKILLS = _PLUGIN / "skills"
_REFERENCE = _PLUGIN / "reference" / "skill_arguments.md"
_POINTER = "${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md"

_INVOCABLE = [
    "a-w", "add-bookmark", "amend-commit-msg", "branch-commit-msg", "bubble-memo", "c-msg", "check-runlogs",
    "d-w", "fold-in-review", "merge-commit-msg", "parallel2", "post-forcepush", "pr-review", "pr-sum", "pr-team",
    "roast-my-code", "sync-gh-todo", "todo-edit", "write-plan",
]
_KNOWLEDGE = [
    "agent-permissions", "consumer-contract-audit", "decompose-module", "efficient-file-reading",
    "searching-sourcegraph", "spatialist", "strap-debugging", "subagent-reporting",
]


def _skill(name: str) -> Path:
    return _SKILLS / name / "SKILL.md"


def _fenced_lines(body: str) -> List[str]:
    inside, lines = False, []
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
        elif inside:
            lines.append(line)
    return lines


def test_every_skill_is_classified() -> None:
    on_disk = sorted(path.parent.name for path in _SKILLS.glob("*/SKILL.md"))
    assert on_disk == sorted(_INVOCABLE + _KNOWLEDGE), "a new skill must join _INVOCABLE or _KNOWLEDGE"


@pytest.mark.parametrize("name", _INVOCABLE)
def test_hint_advertises_the_guidance_tail(name: str) -> None:
    hint = skill_parts(_skill(name))[0].get("argument-hint", "")
    assert "-- <" in hint, f"{name}: argument-hint {hint!r} does not end in the -- <guidance> tail"


@pytest.mark.parametrize("name", _INVOCABLE)
def test_body_points_at_the_split_rule(name: str) -> None:
    assert _POINTER in skill_parts(_skill(name))[1], f"{name}: body never cites {_POINTER}"


@pytest.mark.parametrize("name", _INVOCABLE)
def test_no_fenced_command_carries_the_raw_arguments(name: str) -> None:
    holders = [line for line in _fenced_lines(skill_parts(_skill(name))[1]) if "$ARGUMENTS" in line]
    assert not holders, f"{name}: fenced command lines carry $ARGUMENTS: {holders}"


@pytest.mark.parametrize("name", _KNOWLEDGE)
def test_knowledge_skills_take_no_arguments(name: str) -> None:
    assert "argument-hint" not in skill_parts(_skill(name))[0]


def test_reference_states_the_split_rule() -> None:
    text = _REFERENCE.read_text(encoding="utf-8")
    for needle in ("first standalone `--` token", "Developer guidance:", "never lands on a command line"):
        assert needle in text, f"reference never says {needle!r}"
