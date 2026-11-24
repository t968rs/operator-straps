"""Guard test: ``strap-debugging`` stands alone, and the debugging pointers lead to it first.

The skill came over from an outside systematic-debugging skill as its stand-in, so its trigger waited on that
plugin being absent and the session rules and check-runlogs named the outside skill first. With the source
plugin retiring, a pointer to it leads nowhere; the test pins every route into debugging on the bundled skill.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _skill_parts import skill_parts  # noqa: E402

_PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_SKILL = _PLUGIN / "skills" / "strap-debugging" / "SKILL.md"
_RUNLOGS = _PLUGIN / "skills" / "check-runlogs" / "SKILL.md"
_RULES = _PLUGIN / "rules" / "HARNESS_RULES.md"


def test_the_skill_triggers_on_its_own() -> None:
    meta, body = skill_parts(_SKILL)
    assert meta["description"].startswith("Use when")
    assert "not installed" not in meta["description"], "the trigger waits on another plugin being absent"
    assert "superpowers" not in (meta["description"] + body).lower(), "a pointer names the source plugin"


def test_check_runlogs_loads_the_bundled_skill() -> None:
    body = skill_parts(_RUNLOGS)[1]
    assert "harness:strap-debugging" in body
    assert "systematic-debugging" not in body, "the investigator still reaches for the source skill"


def test_the_troubleshooting_rule_names_the_bundled_skill() -> None:
    text = _RULES.read_text(encoding="utf-8")
    rule = re.search(r"^- \*\*Troubleshooting:\*\*.*?(?=^- )", text, re.M | re.S)
    assert rule, "HARNESS_RULES.md has no Troubleshooting rule"
    assert "harness:strap-debugging" in rule.group(0)
    assert "superpowers" not in rule.group(0).lower(), "the rule names the source skill"
