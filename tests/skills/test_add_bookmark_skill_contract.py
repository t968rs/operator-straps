"""Guard test: the add-bookmark skill, the bookmark-noter agent and ``add_note.py`` agree.

The skill forks into the agent; the agent runs the script. All three are named in prose, so the test pins the
names, the model, the tool list and the limits they share.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Dict

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_SKILL = _PLUGIN_ROOT / "skills" / "add-bookmark" / "SKILL.md"
_AGENT = _PLUGIN_ROOT / "agents" / "bookmark-noter.md"
_SCRIPT = _PLUGIN_ROOT / "skills" / "add-bookmark" / "commands" / "add_note.py"


def _text(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"missing {path}")
    return path.read_text(encoding="utf-8")


def _frontmatter(path: Path) -> Dict[str, str]:
    block = re.match(r"^---\n(.*?)\n---\n", _text(path), re.DOTALL)
    assert block, f"{path.name} has no frontmatter"
    pairs = (line.split(":", 1) for line in block.group(1).splitlines() if re.match(r"^[a-z-]+:", line))
    return {key.strip(): value.strip() for key, value in pairs}


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("add_note_guard", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_forks_into_the_noter_on_haiku() -> None:
    meta = _frontmatter(_SKILL)
    assert meta["name"] == "add-bookmark"
    assert meta["context"] == "fork"
    assert meta["agent"] == "harness:bookmark-noter"
    assert meta["model"] == "haiku"


def test_skill_hints_every_form() -> None:
    hint = _frontmatter(_SKILL)["argument-hint"]
    assert "--list" in hint and "--clear" in hint


def test_skill_passes_the_arguments_to_the_agent() -> None:
    assert "$ARGUMENTS" in _text(_SKILL)


def test_agent_is_haiku_with_bash_only() -> None:
    meta = _frontmatter(_AGENT)
    assert meta["name"] == "bookmark-noter"
    assert meta["model"] == "haiku"
    assert meta["tools"] == "Bash"


def test_agent_names_the_script_and_each_subcommand() -> None:
    body = _text(_AGENT)
    assert "skills/add-bookmark/commands/add_note.py" in body
    for subcommand in ("add", "list", "clear"):
        assert f"NOTE {subcommand}" in body, f"agent never runs NOTE {subcommand}"


def test_skill_and_agent_state_the_script_limits(script) -> None:
    for path in (_SKILL, _AGENT):
        text = _text(path)
        assert re.search(rf"at most {script.MAX_NOTES} notes", text), f"{path.name}: note count"
        assert re.search(rf"at most {script.MAX_NOTE_CHARS} characters", text), f"{path.name}: length"


def test_agent_treats_the_note_as_data_and_may_not_edit_files() -> None:
    body = _text(_AGENT).lower()
    assert "data to record" in body and "not an instruction" in body
    assert "no other command" in body
