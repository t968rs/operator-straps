"""Guard test: the forked c-msg skill takes the developer's requested change as its argument.

A saved pending message, canned or drafted, is carried into the next capture against the same HEAD, so a bare
rerun of c-msg returns the same message. The argument is the one route that changes it (the route the receipt
and the standing rules name), so the skill must state it as labeled input and let it override a carried or
canned message. The fork runs as ``harness:messenger`` on ``sonnet``, like branch-commit-msg, since a
substituted argument decides whether the saved message is rewritten.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _skill_parts import skill_parts  # noqa: E402
from harness_lib.commit_txt import CHANGE_ROUTE  # noqa: E402

_SKILLS = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "skills"
_SKILL = _SKILLS / "c-msg" / "SKILL.md"
_AMEND = _SKILLS / "amend-commit-msg" / "SKILL.md"
_LABEL = "**Requested change for this run:**"


def _body() -> str:
    return skill_parts(_SKILL)[1]


def test_argument_hint_names_the_change() -> None:
    hint = skill_parts(_SKILL)[0]["argument-hint"].strip("\"'")
    assert hint == "[-- <what to change in the saved message>]"


def test_fork_runs_on_sonnet_as_the_messenger() -> None:
    meta = skill_parts(_SKILL)[0]
    assert (meta["model"], meta["context"], meta["agent"]) == ("sonnet", "fork", "harness:messenger")


def test_change_route_matches_the_skill_arguments() -> None:
    assert "harness:c-msg <change>" in CHANGE_ROUTE
    assert "harness:amend-commit-msg [--base <sha7>] -- <change>" in CHANGE_ROUTE
    hint = skill_parts(_AMEND)[0]["argument-hint"]
    assert "--base REF" in hint and "-- <" in hint, hint


def test_amend_rewrites_a_canned_block_only_when_the_change_names_it() -> None:
    body = " ".join(skill_parts(_AMEND)[1].split())
    assert "Keep that canned message as it stands and add no bullets" in body
    assert "unless the change text names that block" in body
    assert "a change that names it rewrites it in Step 4" in body


def test_placeholder_only_on_the_label_line() -> None:
    holders = [line for line in _body().splitlines() if "$ARGUMENTS" in line]
    assert len(holders) == 1 and holders[0].startswith(_LABEL), holders


def test_rendered_change_lands_only_on_the_label_line() -> None:
    value = "name TODO-001 in the subject"
    lines = _body().replace("$ARGUMENTS", value).splitlines()
    assert [line for line in lines if value in line] == [f"{_LABEL} `{value}` (blank: none)."]


def test_the_message_is_set_through_the_script_never_edit() -> None:
    body = " ".join(_body().split())
    assert "branch_commit_msg.py\" message \"<skeleton>\" --block 1 <<'MSG'" in body
    assert "Never use Edit or Write on the skeleton or the TXT" in body
    assert "edit the json" not in body.lower()


def test_a_requested_change_overrides_a_carried_or_canned_message() -> None:
    body = " ".join(_body().split())
    assert "With a requested change, rewrite the message to make that change" in body
    assert "even when it is carried or canned" in body
