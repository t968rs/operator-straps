"""Guard test: the forked c-msg skill takes the developer's requested change as its argument.

A saved pending message, canned or drafted, is carried into the next capture against the same HEAD, so a bare
rerun of c-msg returns the same message. The argument is the one route that changes it (the route the receipt
and the standing rules name), so the skill must state it as labeled input and let it override a carried or
canned message.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

_SKILL = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "skills" / "c-msg" / "SKILL.md"
_LABEL = "**Requested change for this run:**"


def _split() -> List[str]:
    parts = re.match(r"^---\n(.*?)\n---\n(.*)$", _SKILL.read_text(encoding="utf-8"), re.DOTALL)
    assert parts, "SKILL.md has no frontmatter"
    return [parts.group(1), parts.group(2)]


def _frontmatter() -> Dict[str, str]:
    pairs = (line.split(":", 1) for line in _split()[0].splitlines() if re.match(r"^[a-z-]+:", line))
    return {key.strip(): value.strip() for key, value in pairs}


def test_argument_hint_names_the_change() -> None:
    assert _frontmatter()["argument-hint"].strip("\"'") == "[what to change in the saved message]"


def test_placeholder_only_on_the_label_line() -> None:
    holders = [line for line in _split()[1].splitlines() if "$ARGUMENTS" in line]
    assert len(holders) == 1 and holders[0].startswith(_LABEL), holders


def test_rendered_change_lands_only_on_the_label_line() -> None:
    value = "name TODO-001 in the subject"
    lines = _split()[1].replace("$ARGUMENTS", value).splitlines()
    assert [line for line in lines if value in line] == [f"{_LABEL} `{value}` (blank: none)."]


def test_a_requested_change_overrides_a_carried_or_canned_message() -> None:
    body = " ".join(_split()[1].split())
    assert "With a requested change, rewrite the message to make that change" in body
    assert "even when it is carried or canned" in body
