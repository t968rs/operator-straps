"""Guard test: the messenger agent never re-reads a forked skill's SKILL.md from disk.

A forked skill (``context: fork``) hands the agent its body with ``$ARGUMENTS`` already substituted; the copy
on disk holds the bare placeholder, which Bash expands to nothing. The test pins that the operating rules say
so.
"""
from __future__ import annotations

import re
from pathlib import Path

_AGENT = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "agents" / "messenger.md"


def _operating_rules() -> str:
    text = _AGENT.read_text(encoding="utf-8")
    section = re.search(r"^## Operating rules\n(.*?)^## ", text, re.DOTALL | re.MULTILINE)
    assert section, "messenger.md has no Operating rules section"
    return section.group(1)


def test_forked_skill_prompt_is_not_reread() -> None:
    rules = _operating_rules()
    assert "Base directory for this skill:" in rules
    assert "$ARGUMENTS" in rules
    assert re.search(r"do not read its\s+`SKILL\.md`", rules)


def test_a_named_skill_is_still_read_first() -> None:
    assert "read its `SKILL.md` first" in _operating_rules()


def test_a_skill_read_from_disk_gets_the_dispatchers_arguments() -> None:
    rules = " ".join(_operating_rules().split())
    assert ("replace every `$ARGUMENTS` in it with the arguments the dispatcher's prompt gives "
            "(nothing when it gives none) before running any command") in rules
