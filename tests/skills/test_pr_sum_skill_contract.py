"""Contract of the pr-sum skill: ``--auto-title`` is the developer's consent, the only route to a rename.

The argument hint names the flag, the capture step states the consent, and Common Mistakes bans adding the
flag or running ``gh pr edit`` unasked.
"""
from __future__ import annotations

from conftest import PLUGIN_ROOT
from harness_lib.skill_parts import skill_parts

NAME = "pr-sum"
SKILL = PLUGIN_ROOT / "skills" / NAME / "SKILL.md"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def test_frontmatter_names_the_skill_folder() -> None:
    assert skill_parts(SKILL)[0]["name"].strip("\"'") == NAME


def test_argument_hint_names_the_auto_title_flag() -> None:
    assert "[--auto-title]" in skill_parts(SKILL)[0].get("argument-hint", "")


def test_skill_gates_retitle_on_the_auto_title_flag() -> None:
    text = _text()
    assert "`--auto-title` is the developer's consent to rename the PR" in text
    assert "Never choose a level, a `--min-viz` count, `--auto-title`" in text
    assert "`gh pr edit`, unasked" in _section(text, "## Common Mistakes")
