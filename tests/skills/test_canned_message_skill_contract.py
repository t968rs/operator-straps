"""Guard test: the commit-message skills and ``branch_commit_msg.py`` agree on canned messages.

``capture`` prefills a block whose files are a canned set (``harness_lib.canned_messages``), and ``canned``
prints the message for a file list. The skills name both in prose, so the test pins that each skill says what
to do with a prefilled message and that the merge skill's ``canned`` line parses with the script's parser.
"""
from __future__ import annotations

import importlib.util
import re
import shlex
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_SKILLS = _PLUGIN_ROOT / "skills"
_SCRIPT = _PLUGIN_ROOT / "scripts" / "branch_commit_msg.py"
_LAUNCHER = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/branch_commit_msg.py"'
_CAPTURE_SKILLS = ("c-msg", "branch-commit-msg", "amend-commit-msg")


def _text(skill: str) -> str:
    return (_SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parser():
    spec = importlib.util.spec_from_file_location("branch_commit_msg_canned_guard", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._parser()


@pytest.mark.parametrize("skill", _CAPTURE_SKILLS)
def test_capture_skills_keep_a_canned_message(skill: str) -> None:
    body = _text(skill)
    assert "canned" in body, f"{skill} never mentions the canned message a capture can prefill"
    assert "canned_messages.py" in body, f"{skill} does not point at the module that owns the entries"


@pytest.mark.parametrize("skill", ["c-msg", "branch-commit-msg"])
def test_a_prefilled_block_is_not_redrafted(skill: str) -> None:
    body = _text(skill)
    assert re.search(r"canned[^\n]*(skip|keep|as it stands)|(skip|keep)[^\n]*canned", body, re.IGNORECASE)


def test_merge_skill_asks_the_script_for_the_canned_message(parser) -> None:
    lines = re.findall(rf"{re.escape(_LAUNCHER)} (canned\b.*)$", _text("merge-commit-msg"), re.MULTILINE)
    assert lines, "merge-commit-msg never runs the canned subcommand"
    for line in lines:
        args = parser.parse_args(shlex.split(line))
        assert args.command == "canned"


def test_merge_skill_feeds_the_canned_command_the_pr_files() -> None:
    body = _text("merge-commit-msg")
    assert re.search(r"gh pr diff NNN --name-only \| " + re.escape(_LAUNCHER) + r" canned", body)
