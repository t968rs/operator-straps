"""Guard test: the forked branch-commit-msg skill hands the developer's arguments to its agent as input.

With ``context: fork`` the skill body, ``$ARGUMENTS`` substituted, is the whole prompt of the forked agent.
A value substituted into prose next to the flags table reads as one more example, and a fork once dropped a
developer's ``--base`` that way. The tests render the body the way Claude Code does and pin that the value
lands only on the labeled arguments line (the capture command carries the pre-``--`` part, never the raw
value), and that the fork runs on ``sonnet``.
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


def test_arguments_placeholder_only_on_the_label() -> None:
    holders = [line for line in _body().splitlines() if "$ARGUMENTS" in line]
    assert len(holders) == 1 and holders[0].startswith(_LABEL), holders


def test_capture_command_carries_the_pre_split_placeholder() -> None:
    commands = [line for line in _body().splitlines() if _CAPTURE.search(line)]
    assert len(commands) == 1 and commands[0].rstrip().endswith("<capture arguments>"), commands


def test_label_sits_under_the_title_and_names_the_split() -> None:
    body = [line for line in _body().splitlines() if line.strip()]
    assert body[0].startswith("# branch-commit-msg")
    assert body[1].startswith(_LABEL)
    assert "not an example" in body[2] and "`<capture arguments>` in Step 1" in " ".join(body[2:5])


@pytest.mark.parametrize(
    "value", ["--base 21df29c52", "21df29c52 --fresh", "--base origin/dev -- keep docs apart"]
)
def test_rendered_value_lands_only_on_the_label(value: str) -> None:
    holders = [line for line in _rendered(value) if value in line]
    assert holders == [f"{_LABEL} `{value}` (blank: none)."], holders


def test_blank_arguments_read_as_none() -> None:
    assert f"{_LABEL} `` (blank: none)." in _rendered("")


def test_argument_hint_lists_the_merge_flag() -> None:
    assert "[--merge-msg]" in _frontmatter()["argument-hint"]


def test_merge_step_runs_after_build_and_names_the_merge_skill() -> None:
    body = _body()
    assert body.index("## Step 4") < body.index("## Step 5")
    step = body[body.index("## Step 5"):body.index("## Common Mistakes")]
    assert "--merge-msg" in step
    assert "${CLAUDE_PLUGIN_ROOT}/skills/merge-commit-msg/SKILL.md" in step
    assert "$ARGUMENTS" not in step, "the arguments value may land only on the label and the capture command"


def test_merge_flag_parses_with_the_capture_command() -> None:
    import importlib.util

    script = _SKILLS.parent / "scripts" / "branch_commit_msg.py"
    spec = importlib.util.spec_from_file_location("branch_commit_msg_flag_guard", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = module._parser().parse_args(["capture", "--save", "--merge-msg"])
    assert args.merge_msg is True


def test_fork_runs_on_sonnet() -> None:
    meta = _frontmatter()
    assert (meta["model"], meta["context"], meta["agent"]) == ("sonnet", "fork", "harness:messenger")
