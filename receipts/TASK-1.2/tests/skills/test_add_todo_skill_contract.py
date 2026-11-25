"""Contract test for the ``add-todo`` skill: its SKILL.md, its driver call, its models and the agent it
dispatches.

The skill's models and API are imported, never copied: a literal pinned here would drift from the module that
defines it.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from harness_lib import add_todo_api as api
from harness_lib.add_todo_models import AddTodoRequest
from harness_lib.project import plugin_root
from harness_lib.skill_parts import skill_parts

NAME = "add-todo"
SKILL = plugin_root() / "skills" / NAME / "SKILL.md"
AGENT = plugin_root() / "agents" / "todo-editor.md"
DRIVER = 'scripts/add_todo.py" row'


def test_frontmatter_names_the_skill_folder() -> None:
    keys = skill_parts(SKILL)[0]
    assert keys["name"].strip("\"'") == NAME


def test_description_is_filled() -> None:
    description = skill_parts(SKILL)[0].get("description", "").strip("\"'")
    assert description.startswith("Use when"), description


def test_skill_runs_the_driver_row() -> None:
    assert DRIVER in skill_parts(SKILL)[1]


def test_skill_dispatches_the_agent_the_row_names() -> None:
    assert f'subagent_type="{api.AGENT}"' in skill_parts(SKILL)[1]


def test_api_exports_existing_names() -> None:
    missing = [name for name in api.__all__ if not hasattr(api, name)]
    assert not missing, missing


def test_request_forbids_extra_keys() -> None:
    with pytest.raises(ValidationError):
        AddTodoRequest.model_validate({"issue": True, "unexpected": 1})


def test_agent_documents_the_add_operation() -> None:
    text = AGENT.read_text(encoding="utf-8")
    assert "\n## add\n" in text
    frontmatter = text.split("---")[1]
    assert "harness:add-todo" in frontmatter
