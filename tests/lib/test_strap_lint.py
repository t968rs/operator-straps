"""Behavioral tests for harness_lib.strap_lint and the moved harness_lib.skill_parts parser.

Pins the ``skill_parts`` split of a SKILL.md into literal keys and body, ``is_invocable`` (``$ARGUMENTS`` in
the body or an ``argument-hint`` key, D18), and each ``lint_skill`` rule on skills written into a throwaway
plugin directory: the missing SKILL.md stop, the name match, the description rules (fixed prefix message,
one pair of matching quotes stripped first), the invocable and knowledge argument rules, fenced
``$ARGUMENTS``, unresolved script, skill, agent and ``harness_lib`` module references, bare interpreter calls
in fences and vendor names (product and variable spellings excepted). ``lint_python`` flags first and second
person only in comments and docstrings. The shipped ``write-plan`` skill lints clean, and the shipped
``pr-sum`` (hint only) and ``spatialist`` skills classify as invocable and knowledge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import pytest

from harness_lib.skill_parts import skill_parts
from harness_lib.strap_lint import is_invocable, lint_python, lint_skill

_NAME = "demo"
_BARE = "Clau" + "de"
_VENDORS = ("Anthro" + "pic", "Open" + "AI", "Chat" + "GPT", "Gem" + "ini", _BARE)
_HINT = '"<target> [-- <guidance>]"'
_DESCRIPTION = 'Use when a demo needs running. Triggers on "demo", "run the demo".'
_PREFIX_PROBLEM = f"{_NAME}: description does not start with 'Use when'"
_REFERENCE_LINE = ("Split them at the first standalone `--` token, per "
                   "`${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`.\n\n")
_INVOCABLE_BODY = (
    "# demo\n\n"
    "Arguments: `$ARGUMENTS`\n\n"
    + _REFERENCE_LINE
    + "```bash\n"
    'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/tool.py" run\n'
    "```\n\n"
    "Dispatch `harness:helper` for each lane, then dispatch `harness:other`.\n"
    "Layout: `${CLAUDE_PLUGIN_ROOT}/skills/demo/SKILL.md`.\n"
)
_KNOWLEDGE_BODY = "# demo\n\nRead the table before editing.\n"
_HINT_ONLY_BODY = "# demo\n\n" + _REFERENCE_LINE + "Read the table before editing.\n"
_PLUGIN_FILES = ("scripts/hpy", "scripts/tool.py", "agents/helper.md", "skills/other/SKILL.md",
                 "reference/skill_arguments.md")


@pytest.fixture()
def plugin(tmp_path: Path) -> Path:
    """A throwaway plugin directory holding the scripts, agent and skill the sample skills name."""
    root = tmp_path / "plug"
    for rel in _PLUGIN_FILES:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n", encoding="utf-8")
    return root


def _front(**changes: Optional[str]) -> Dict[str, str]:
    """The clean invocable frontmatter with ``changes`` applied (None drops a key)."""
    keys = {"name": _NAME, "description": _DESCRIPTION, "argument-hint": _HINT}
    keys.update({key.replace("_", "-"): value for key, value in changes.items()})
    return {key: value for key, value in keys.items() if value is not None}


def _write_skill(plugin: Path, front: Dict[str, str], body: str, folder: str = _NAME) -> Path:
    """Write ``plugin/skills/<folder>/SKILL.md`` from ``front`` and ``body``."""
    head = "".join(f"{key}: {value}\n" for key, value in front.items())
    path = plugin / "skills" / folder / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{head}---\n\n{body}", encoding="utf-8")
    return path


def _one_problem(problems: List[str], name: str = _NAME) -> None:
    """Exactly one problem, prefixed with the skill name."""
    assert len(problems) == 1, problems
    assert problems[0].startswith(f"{name}: "), problems


def _lint_body(plugin: Path, extra: str) -> List[str]:
    """Lint the clean invocable skill with ``extra`` appended to its body."""
    _write_skill(plugin, _front(), _INVOCABLE_BODY + extra)
    return lint_skill(plugin, _NAME)


def test_skill_parts_parses_keys_and_body(tmp_path: Path) -> None:
    sample = tmp_path / "SKILL.md"
    sample.write_text('---\nname: demo\ndescription: Use when x: y.\nargument-hint: "<a>"\n  more\n---\n'
                      "\n# Body\n\nText: here.\n", encoding="utf-8")
    keys, body = skill_parts(sample)
    assert keys == {"name": "demo", "description": "Use when x: y.", "argument-hint": '"<a>"'}
    assert body == "\n# Body\n\nText: here.\n"


def test_skill_parts_rejects_missing_frontmatter(tmp_path: Path) -> None:
    sample = tmp_path / "SKILL.md"
    sample.write_text("# No frontmatter\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        skill_parts(sample)


def test_clean_invocable_skill_has_no_problems(plugin: Path) -> None:
    _write_skill(plugin, _front(), _INVOCABLE_BODY)
    assert lint_skill(plugin, _NAME) == []


def test_missing_skill_md_is_the_only_problem(plugin: Path) -> None:
    assert lint_skill(plugin, "absent") == ["absent: no SKILL.md"]


def test_frontmatter_name_must_match_folder(plugin: Path) -> None:
    _write_skill(plugin, _front(name="other-name"), _INVOCABLE_BODY)
    _one_problem(lint_skill(plugin, _NAME))


def test_description_prefix_message_is_fixed(plugin: Path) -> None:
    _write_skill(plugin, _front(description="Runs the demo. Triggers on demo."), _INVOCABLE_BODY)
    assert lint_skill(plugin, _NAME) == [_PREFIX_PROBLEM]


@pytest.mark.parametrize("description", [
    pytest.param("Use when " + "a" * 1100, id="too-long"),
    pytest.param("Use when you need a demo.", id="you"),
    pytest.param("Use when your demo stalls.", id="your"),
    pytest.param("Use when we run a demo.", id="we"),
    pytest.param("Use when I run a demo.", id="I"),
])
def test_description_rules(plugin: Path, description: str) -> None:
    _write_skill(plugin, _front(description=description), _INVOCABLE_BODY)
    _one_problem(lint_skill(plugin, _NAME))


@pytest.mark.parametrize("changes", [
    pytest.param({"description": "'Use when a demo needs running: \"demo\" or \"run it\".'"},
                 id="single-quoted-description"),
    pytest.param({"description": '"Use when a demo needs running."'}, id="double-quoted-description"),
    pytest.param({"name": '"demo"'}, id="double-quoted-name"),
])
def test_quoted_frontmatter_values_pass(plugin: Path, changes: Dict[str, str]) -> None:
    _write_skill(plugin, _front(**changes), _INVOCABLE_BODY)
    assert lint_skill(plugin, _NAME) == []


def test_mismatched_quotes_are_not_stripped(plugin: Path) -> None:
    _write_skill(plugin, _front(description="'Use when a demo needs running.\""), _INVOCABLE_BODY)
    assert lint_skill(plugin, _NAME) == [_PREFIX_PROBLEM]


def test_missing_description_is_flagged(plugin: Path) -> None:
    _write_skill(plugin, _front(description=None), _INVOCABLE_BODY)
    problems = lint_skill(plugin, _NAME)
    assert problems, "a skill without a description lints clean"
    assert all(problem.startswith(f"{_NAME}: ") for problem in problems), problems


@pytest.mark.parametrize("front, body, expected", [
    pytest.param({"name": _NAME}, "Arguments: `$ARGUMENTS`\n", True, id="arguments-in-body"),
    pytest.param({"name": _NAME, "argument-hint": _HINT}, "# demo\n", True, id="hint-only"),
    pytest.param({"name": _NAME}, "# demo\n", False, id="neither"),
])
def test_is_invocable_classification(front: Dict[str, str], body: str, expected: bool) -> None:
    assert is_invocable(front, body) is expected


@pytest.mark.parametrize("skill, expected", [
    pytest.param("pr-sum", True, id="pr-sum"),
    pytest.param("spatialist", False, id="spatialist"),
])
def test_is_invocable_on_shipped_skill(plugin_root: Path, skill: str, expected: bool) -> None:
    path = plugin_root / "skills" / skill / "SKILL.md"
    assert path.is_file(), path
    keys, body = skill_parts(path)
    assert is_invocable(keys, body) is expected


@pytest.mark.parametrize("hint, body", [
    pytest.param(None, _INVOCABLE_BODY, id="hint-missing"),
    pytest.param('"<target> [--flag]"', _INVOCABLE_BODY, id="hint-lacks-guidance"),
    pytest.param(_HINT, _INVOCABLE_BODY.replace(_REFERENCE_LINE, ""), id="reference-missing"),
])
def test_invocable_argument_rules(plugin: Path, hint: Optional[str], body: str) -> None:
    _write_skill(plugin, _front(argument_hint=hint), body)
    _one_problem(lint_skill(plugin, _NAME))


def test_hint_only_skill_with_reference_is_clean(plugin: Path) -> None:
    _write_skill(plugin, _front(), _HINT_ONLY_BODY)
    assert lint_skill(plugin, _NAME) == []


def test_hint_only_skill_lacking_reference_flagged(plugin: Path) -> None:
    _write_skill(plugin, _front(), _KNOWLEDGE_BODY)
    _one_problem(lint_skill(plugin, _NAME))


def test_fenced_arguments_line_is_flagged(plugin: Path) -> None:
    _one_problem(_lint_body(plugin, "\n```bash\necho $ARGUMENTS\n```\n"))


def test_knowledge_skill_without_hint_is_clean(plugin: Path) -> None:
    _write_skill(plugin, _front(argument_hint=None), _KNOWLEDGE_BODY)
    assert lint_skill(plugin, _NAME) == []


@pytest.mark.parametrize("extra", [
    pytest.param("Run `${CLAUDE_PLUGIN_ROOT}/scripts/gone.py` first.\n", id="script"),
    pytest.param("See `${CLAUDE_PLUGIN_ROOT}/skills/gone/SKILL.md`.\n", id="skill"),
    pytest.param("Dispatch `harness:ghost` for the review.\n", id="agent"),
    pytest.param("Bind `harness_lib.ghost_api` through the launcher.\n", id="harness-lib"),
])
def test_unresolved_reference_is_flagged(plugin: Path, extra: str) -> None:
    _one_problem(_lint_body(plugin, extra))


def test_named_harness_lib_module_resolves(plugin: Path) -> None:
    module = plugin / "lib" / "harness_lib" / "demo_api.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text("X = 1\n", encoding="utf-8")
    assert _lint_body(plugin, "Bind `harness_lib.demo_api` through the launcher.\n") == []


@pytest.mark.parametrize("command", ["python -m demo", "python3 -m demo"])
def test_bare_interpreter_in_fence_is_flagged(plugin: Path, command: str) -> None:
    _one_problem(_lint_body(plugin, f"\n```bash\n{command}\n```\n"))


@pytest.mark.parametrize("vendor", _VENDORS)
def test_vendor_name_is_flagged(plugin: Path, vendor: str) -> None:
    _one_problem(_lint_body(plugin, f"Works with {vendor} tools.\n"))


def test_product_and_variable_spellings_pass(plugin: Path) -> None:
    extra = f"Runs in {_BARE} Code, reads CLAUDE.md and " + "`${CLAUDE_SKILL_DIR}/notes.md`.\n"
    assert _lint_body(plugin, extra) == []


@pytest.mark.parametrize("source", [
    pytest.param('"""Module text that you read."""\nX = 1\n', id="module-docstring"),
    pytest.param("X = 1  # we keep this\n", id="inline-comment"),
    pytest.param('def f() -> int:\n    """Return our value."""\n    return 1\n', id="function-docstring"),
    pytest.param("# I wrote this\nX = 1\n", id="line-comment"),
    pytest.param('class K:\n    """Your class."""\n', id="class-docstring"),
])
def test_lint_python_flags_person_in_comments(tmp_path: Path, source: str) -> None:
    path = tmp_path / "mod.py"
    path.write_text(source, encoding="utf-8")
    assert lint_python(path), source


def test_lint_python_ignores_code_and_string_literals(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text('"""Pin values."""\nyou_x = 1\nmessage = "you and your team"\nhashed = "# we here"\n\n\n'
                    'def f(i: int) -> int:\n    """Return the doubled value."""\n'
                    "    return i * 2  # double i\n", encoding="utf-8")
    assert lint_python(path) == []


def test_shipped_write_plan_skill_is_clean(plugin_root: Path) -> None:
    assert (plugin_root / "skills" / "write-plan" / "SKILL.md").is_file()
    assert lint_skill(plugin_root, "write-plan") == []
