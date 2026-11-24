"""Guard test: the ``tdd-strapped`` skill stands alone and keeps the project's test-scoping rules.

The skill is a port of an outside test-driven-development skill. A port that drifts back toward the source
brings two breaks this test catches: a trigger or pointer that assumes the source plugin is installed, and a
fenced verification step that runs the whole suite or a directory, which the scoping rules leave to the
developer. The run check covers the runner spellings in ``_TEST_COMMAND``; a fenced run passes only when
a token names a test file (by extension) or a node id (``::``), so a folder or a path-valued flag fails.

These checks pin structure another skill or loader consumes (frontmatter, cross-skill pointers, the linked
reference, the absence of a pointer to a plugin that may be missing) and the two scoping sentences, a
deliberate pin on a port that drifts toward its source. The skill's behavior is proven by the strap round
(``harness:strap-skills``), which writing-good-tests.md names as the home for behavior claims.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _skill_parts import skill_parts  # noqa: E402

_FOLDER = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "skills" / "tdd-strapped"
_SKILL = _FOLDER / "SKILL.md"
_REFERENCE = _FOLDER / "writing-good-tests.md"
_RULES = _FOLDER.parents[1] / "rules" / "HARNESS_RULES.md"
_TEST_COMMAND = re.compile(
    r"\bpytest\b|\bpython -m unittest\b|\b(?:npm|yarn|pnpm) test\b|\bnpx (?:jest|vitest)\b"
    r"|\bcargo test\b|\bgo test\b"
)
_FENCE = re.compile(r"^\s*(```|~~~)")
_TARGET_TOKEN = re.compile(r"^[^-]\S*(?:\.(?:py|tsx?|jsx?|mjs|cjs|rs|go)(?:::\S+)?|::\S+)$")


def _names_target(line: str) -> bool:
    return any(_TARGET_TOKEN.match(token) for token in line.split())


def _texts() -> List[str]:
    return [_SKILL.read_text(encoding="utf-8"), _REFERENCE.read_text(encoding="utf-8")]


def _fenced(text: str) -> List[str]:
    inside, fence, lines = False, "", []
    for line in text.splitlines():
        opener = _FENCE.match(line)
        if opener and not inside:
            inside, fence = True, opener.group(1)
        elif opener and opener.group(1) == fence:
            inside = False
        elif inside:
            lines.append(line.strip())
    return lines


def test_the_skill_triggers_on_its_own() -> None:
    meta = skill_parts(_SKILL)[0]
    assert meta["name"] == "tdd-strapped"
    assert meta["description"].startswith("Use when")
    assert "not installed" not in meta["description"], "the trigger waits on another plugin being absent"


def test_no_pointer_reaches_outside_the_marketplace_plugins() -> None:
    for text in _texts():
        assert "superpowers" not in text.lower(), "a pointer names the source plugin"
        assert "human partner" not in text.lower(), "the source's voice for the developer survived"


def test_every_fenced_test_run_names_its_target() -> None:
    runs = [line for text in _texts() for line in _fenced(text) if _TEST_COMMAND.search(line)]
    assert runs, "the skill shows no test run at all"
    bare = [line for line in runs if not _names_target(line)]
    assert not bare, f"test runs without a named file or node id: {bare}"


def test_the_target_check_rejects_folders_and_flags() -> None:
    assert not _names_target("pytest tests/unit")
    assert not _names_target("npm test src/components")
    assert not _names_target("pytest -q --junitxml=out/report.xml")
    assert _names_target("npm test src/form.test.ts")
    assert _names_target("pytest tests/x.py::test_a")


def test_the_suite_run_belongs_to_the_developer() -> None:
    body = " ".join(skill_parts(_SKILL)[1].split()).lower()
    assert "name files or node ids, never a directory" in body, "no rule that a run names its files"
    suite_rule = "full-suite runs belong to the developer"
    assert suite_rule in body, f"no rule that {suite_rule}"


def test_the_writing_code_rule_names_the_bundled_skill() -> None:
    text = _RULES.read_text(encoding="utf-8")
    rule = re.search(r"^- \*\*Writing code:\*\*.*?(?=^- )", text, re.M | re.S)
    assert rule, "HARNESS_RULES.md has no Writing code rule"
    assert "harness:tdd-strapped" in rule.group(0)
    assert "superpowers" not in rule.group(0).lower(), "the rule names the source skill"


def test_the_reference_is_linked_and_licensed() -> None:
    assert "(writing-good-tests.md)" in skill_parts(_SKILL)[1]
    assert (_FOLDER / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
