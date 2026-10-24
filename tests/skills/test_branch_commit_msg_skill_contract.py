"""Guard test: the forked branch-commit-msg skill hands the developer's arguments to its agent as input.

With ``context: fork`` the skill body, ``$ARGUMENTS`` substituted, is the whole prompt of the forked agent.
A value substituted into prose next to the flags table reads as one more example, and a fork once dropped a
developer's ``--base`` that way. The tests render the body the way Claude Code does and pin that the value
lands only on the labeled arguments line and on the capture command, and that the fork runs on ``sonnet``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _skill_parts import skill_parts  # noqa: E402

_SKILLS = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "skills"
_SKILL = _SKILLS / "branch-commit-msg" / "SKILL.md"
_LABEL = "**Arguments for this run:**"
_CAPTURE = re.compile(r'branch_commit_msg\.py" capture --save\b')


def _body() -> str:
    return skill_parts(_SKILL)[1]


def _frontmatter() -> Dict[str, str]:
    return skill_parts(_SKILL)[0]


def _rendered(arguments: str) -> List[str]:
    return _body().replace("$ARGUMENTS", arguments).splitlines()


def test_arguments_placeholder_only_in_the_label_and_command() -> None:
    holders = [line for line in _body().splitlines() if "$ARGUMENTS" in line]
    assert len(holders) == 2 and sum(line.count("$ARGUMENTS") for line in holders) == 2, holders
    assert holders[0].startswith(_LABEL)
    assert _CAPTURE.search(holders[1]) and holders[1].rstrip().endswith("$ARGUMENTS")


def test_label_sits_under_the_title_and_names_the_command() -> None:
    body = [line for line in _body().splitlines() if line.strip()]
    assert body[0].startswith("# branch-commit-msg")
    assert body[1].startswith(_LABEL)
    assert "not an example" in body[2] and "Step 1 command already carries them" in body[2]


@pytest.mark.parametrize("value", ["--base 21df29c52", "21df29c52 --fresh", "--base origin/dev --no-fetch"])
def test_rendered_value_never_lands_in_prose(value: str) -> None:
    holders = [line for line in _rendered(value) if value in line]
    assert len(holders) == 2, holders
    assert holders[0] == f"{_LABEL} `{value}` (blank: none)."
    assert _CAPTURE.search(holders[1]) and holders[1].rstrip().endswith(value)


def test_blank_arguments_read_as_none() -> None:
    assert f"{_LABEL} `` (blank: none)." in _rendered("")


def test_fork_runs_on_sonnet() -> None:
    meta = _frontmatter()
    assert (meta["model"], meta["context"], meta["agent"]) == ("sonnet", "fork", "harness:messenger")
