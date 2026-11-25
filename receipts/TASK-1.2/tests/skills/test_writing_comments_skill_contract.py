"""Contract test for the ``writing-comments`` skill: its frontmatter and the two files its body routes to.

These are structural guards on what the loader and the session consume (the frontmatter, the section
command launched through hpy, the format reference), not checks of the skill's prose. The section command's
behavior is tested in ``tests/lib/test_writing_comments_api.py`` and
``tests/skills/test_comment_sections_command.py``.
"""
from __future__ import annotations

from typing import Dict, Tuple

from harness_lib.project import plugin_root
from harness_lib.skill_parts import skill_parts

NAME = "writing-comments"
FOLDER = plugin_root() / "skills" / NAME
SKILL = FOLDER / "SKILL.md"
COMMAND = ('sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" '
           '"${CLAUDE_PLUGIN_ROOT}/skills/writing-comments/commands/comment_sections.py"')
FORMAT = "${CLAUDE_SKILL_DIR}/comment_format.md"


def _parts() -> Tuple[Dict[str, str], str]:
    assert SKILL.is_file(), f"{SKILL} is missing"
    return skill_parts(SKILL)


def test_frontmatter_names_the_skill_folder() -> None:
    assert _parts()[0]["name"].strip("\"'") == NAME


def test_description_is_a_use_when_trigger_for_python_comments() -> None:
    description = _parts()[0].get("description", "").strip("\"'")
    assert description.startswith("Use when"), description
    assert "comment" in description.lower(), description


def test_the_section_command_runs_through_hpy() -> None:
    assert COMMAND in _parts()[1]
    assert (FOLDER / "commands" / "comment_sections.py").is_file()


def test_the_format_reference_resolves() -> None:
    assert FORMAT in _parts()[1]
    assert (FOLDER / "comment_format.md").is_file()
