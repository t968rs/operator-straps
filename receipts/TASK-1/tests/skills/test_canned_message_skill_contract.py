"""Guard test: the commit-message skills agree on canned messages.

``branch_commit_msg.py capture`` and ``merge_commit_msg.py capture`` prefill a message when the changed files
are a canned set (``harness_lib.canned_messages``). The skills name that in prose, so the test pins that each
skill says what to do with a prefilled message and that the merge skill leaves the lookup to its capture.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_SKILLS = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "skills"
_CAPTURE_SKILLS = ("c-msg", "branch-commit-msg", "amend-commit-msg", "merge-commit-msg")


def _text(skill: str) -> str:
    return (_SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("skill", _CAPTURE_SKILLS)
def test_capture_skills_keep_a_canned_message(skill: str) -> None:
    body = _text(skill)
    assert "canned message" in body, f"{skill} never mentions the canned message a capture can prefill"
    assert "canned_messages.py" in body, f"{skill} does not point at the module that owns the entries"


@pytest.mark.parametrize("skill", _CAPTURE_SKILLS)
def test_a_prefilled_block_is_not_redrafted(skill: str) -> None:
    body = _text(skill)
    assert re.search(r"canned[^\n]*(skip|keep|as it stands)|(skip|keep)[^\n]*canned", body, re.IGNORECASE)


def test_merge_skill_leaves_the_canned_lookup_to_capture() -> None:
    assert "branch_commit_msg.py\" canned" not in _text("merge-commit-msg")
