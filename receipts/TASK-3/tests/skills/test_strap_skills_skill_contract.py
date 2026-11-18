"""The shipped ``strap-skills`` skill: frontmatter, driver steps, agent dispatch, the API heredoc, the lint.

Pins the SKILL.md surface fixed by plan 0002's contract (Skill section) and the four templates ``scaffold``
renders from ``skills/strap-skills/templates/``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _skill_parts import skill_parts  # noqa: E402

_NAME = "strap-skills"
_HINT = "<name> [--edit] [--judge] [-- <guidance>]"
_LAUNCH = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py"'
_POINTER = "${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md"
_SUBCOMMANDS = ("new", "check", "red", "draw", "run", "record-run", "judge-row", "scaffold", "retest",
                "freeze", "api")
_AGENTS = ("harness:strap-scenario-runner", "harness:strap-judge")
_TEMPLATES = ("skill_md.tmpl", "models.tmpl", "api.tmpl", "contract_test.tmpl")
_TABLE_RULE = re.compile(r"^\s*\|\s*:?-{3,}")


def _skill_dir(plugin_root: Path) -> Path:
    return plugin_root / "skills" / _NAME


@pytest.fixture()
def parts(plugin_root: Path) -> Tuple[Dict[str, str], str]:
    path = _skill_dir(plugin_root) / "SKILL.md"
    assert path.is_file(), f"{path} does not exist"
    return skill_parts(path)


def _fenced(body: str) -> List[str]:
    inside, lines = False, []
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
        elif inside:
            lines.append(line)
    return lines


def _verb(line: str) -> str:
    """The subcommand after ``strap.py`` on one command line, skipping a leading ``--repo DIR``."""
    tail = line.split("strap.py", 1)[1].lstrip('"').split()
    if tail[:1] == ["--repo"]:
        tail = tail[2:]
    return tail[0] if tail else ""


def _strap_lines(body: str) -> List[str]:
    return [line.strip() for line in _fenced(body) if "strap.py" in line]


def test_frontmatter_name_and_description(parts: Tuple[Dict[str, str], str]) -> None:
    front, _ = parts
    assert front["name"].strip("\"'") == _NAME
    assert front["description"].strip("\"'").startswith("Use when")


def test_argument_hint_is_the_contract_hint(parts: Tuple[Dict[str, str], str]) -> None:
    front, _ = parts
    assert front.get("argument-hint", "").strip("\"'") == _HINT


def test_split_rule_cited_and_no_fenced_raw_arguments(parts: Tuple[Dict[str, str], str]) -> None:
    _, body = parts
    assert _POINTER in body
    assert not [line for line in _fenced(body) if "$ARGUMENTS" in line]


def test_every_strap_command_goes_through_the_launcher(parts: Tuple[Dict[str, str], str]) -> None:
    _, body = parts
    commands = _strap_lines(body)
    assert commands, "the skill runs no strap.py command"
    assert all(line.startswith(_LAUNCH) for line in commands), commands


def test_every_driver_subcommand_is_named(parts: Tuple[Dict[str, str], str]) -> None:
    _, body = parts
    missing = [sub for sub in _SUBCOMMANDS
               if not re.search(r'strap\.py"?\s+(?:--repo\s+\S+\s+)?' + re.escape(sub) + r"(?![\w-])", body)]
    assert not missing, f"no `strap.py <sub>` for: {missing}"


def test_both_agents_dispatched_with_an_explicit_model(parts: Tuple[Dict[str, str], str]) -> None:
    _, body = parts
    for agent in _AGENTS:
        assert agent in body, agent
    assert "model=" in body, "no explicit model on the Agent dispatch"


def test_exactly_one_api_heredoc(parts: Tuple[Dict[str, str], str]) -> None:
    _, body = parts
    api = [line for line in _strap_lines(body) if _verb(line) == "api"]
    assert len(api) == 1, api
    assert "<<" in api[0], api[0]


def _table_context(lines: List[str], rule: int) -> str:
    return "\n".join(lines[max(0, rule - 6):rule]).lower()


def test_a_judgment_table(parts: Tuple[Dict[str, str], str]) -> None:
    _, body = parts
    lines = body.splitlines()
    rules = [index for index, line in enumerate(lines) if index and _TABLE_RULE.match(line)]
    assert rules, "the skill has no markdown table"
    assert any("judgment" in _table_context(lines, rule) for rule in rules), (
        "no table under a judgment heading"
    )


def test_lint_skill_finds_no_problem(plugin_root: Path) -> None:
    assert (_skill_dir(plugin_root) / "SKILL.md").is_file(), "strap-skills SKILL.md does not exist"
    from harness_lib.strap_lint import lint_skill
    assert lint_skill(plugin_root, _NAME) == []


@pytest.mark.parametrize("template", _TEMPLATES)
def test_scaffold_template_ships(plugin_root: Path, template: str) -> None:
    path = _skill_dir(plugin_root) / "templates" / template
    assert path.is_file(), f"{path} does not exist"
    assert path.read_text(encoding="utf-8").strip(), f"{path} is empty"
