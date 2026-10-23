"""Guard test: the add-bookmark skill and ``add_note.py`` agree.

The skill runs in the main session, the only context that holds the facts a note refers to; the script stores
the line it is given. Both are named in prose, so the test pins the names, the launcher and the limits they
share, and that the skill never hands the note to a context-free agent.
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


def test_skill_runs_in_the_main_session() -> None:
    meta = _frontmatter(_SKILL)
    assert meta["name"] == "add-bookmark"
    for key in ("context", "agent"):
        assert key not in meta, f"{key} would run the note writer without the session's context"
    assert "model" not in meta, "model would hand note writing to a different model than the session's"


def test_skill_body_names_no_agent_to_dispatch() -> None:
    body = _text(_SKILL)
    assert re.search(r"harness:(?!add-bookmark)[a-z-]+", body) is None, "skill names another agent"
    assert "subagent" not in body.lower(), "skill body mentions a subagent"


def test_no_agent_runs_the_note_writer() -> None:
    assert not _AGENT.exists()
    for agent in sorted(_PLUGIN_ROOT.parent.glob("*/agents/*.md")):
        assert "add_note.py" not in agent.read_text(encoding="utf-8"), f"{agent.name} runs the note writer"


def test_skill_hints_every_form() -> None:
    hint = _frontmatter(_SKILL)["argument-hint"]
    assert "--list" in hint and "--clear" in hint


def test_skill_passes_the_arguments_through() -> None:
    assert "$ARGUMENTS" in _text(_SKILL)


def test_skill_runs_the_script_through_the_launcher_with_each_subcommand() -> None:
    body = _text(_SKILL)
    assert 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/add_note.py"' in body
    for subcommand in ("add", "list", "clear"):
        assert f"NOTE {subcommand}" in body, f"skill never runs NOTE {subcommand}"


def test_skill_states_the_script_limits(script) -> None:
    text = _text(_SKILL)
    assert re.search(rf"at most {script.MAX_NOTES} notes", text), "note count"
    assert re.search(rf"at most {script.MAX_NOTE_CHARS} characters", text), "length"


def test_skill_resolves_session_references_without_another_turn() -> None:
    body = _text(_SKILL).lower()
    assert "concrete facts" in body, "no rule that session references become facts"
    assert "same turn" in body, "no rule that the note is stored without a second request"


def test_skill_treats_the_note_as_data_and_runs_nothing_else() -> None:
    body = _text(_SKILL).lower()
    assert "data to record" in body and "not an instruction" in body
    assert "no other command" in body
