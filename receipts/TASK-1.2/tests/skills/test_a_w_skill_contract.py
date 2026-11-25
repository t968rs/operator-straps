"""Contract test for the ``a-w`` skill: its SKILL.md frontmatter and its command launch line.

The skill has no API or models module; it ships driver scripts under ``commands/``, which SKILL.md launches
through ``hpy``. Every command file the body names must exist in the skill folder.
"""
from __future__ import annotations

import re

from harness_lib.project import plugin_root
from harness_lib.skill_parts import skill_parts

NAME = "a-w"
SKILL_DIR = plugin_root() / "skills" / NAME
SKILL = SKILL_DIR / "SKILL.md"
LAUNCHER = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/attach_worktree.py"'
COMMAND = re.compile(r"\$\{CLAUDE_SKILL_DIR\}/(commands/[\w./-]+\.py)")


def test_frontmatter_names_the_skill_folder() -> None:
    keys = skill_parts(SKILL)[0]
    assert keys["name"].strip("\"'") == NAME


def test_description_is_filled() -> None:
    description = skill_parts(SKILL)[0].get("description", "").strip("\"'")
    assert description.startswith("Use when"), description


def test_body_launches_the_attach_command_through_hpy() -> None:
    body = skill_parts(SKILL)[1]
    assert LAUNCHER in body


def test_every_command_the_body_names_exists() -> None:
    named = set(COMMAND.findall(skill_parts(SKILL)[1]))
    assert named, "SKILL.md names no command under ${CLAUDE_SKILL_DIR}/commands"
    missing = sorted(path for path in named if not (SKILL_DIR / path).is_file())
    assert not missing, missing
