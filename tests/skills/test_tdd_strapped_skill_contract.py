"""Guard test: the ``tdd-strapped`` skill stands alone and keeps the project's test-scoping rules.

The skill is a port of an outside test-driven-development skill. A port that drifts back toward the source
brings two breaks this test catches: a trigger or pointer that assumes the source plugin is installed, and a
verification step that runs the whole suite bare, which the scoping rules leave to the developer.
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
_TEST_COMMAND = re.compile(r"(?:^|\$ )(?:npm test|pytest|python -m pytest|cargo test|go test)\b")
_NAMED_TARGET = re.compile(r"\S+(?:/|\\)\S+|\S+\.(?:py|ts|js|rs|go)\b|::")


def _texts() -> List[str]:
    return [_SKILL.read_text(encoding="utf-8"), _REFERENCE.read_text(encoding="utf-8")]


def _fenced(text: str) -> List[str]:
    inside, lines = False, []
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
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
        assert "superpowers" not in text, "a pointer names the source plugin"
        assert "human partner" not in text.lower(), "the source's voice for the developer survived"


def test_every_fenced_test_run_names_its_target() -> None:
    runs = [line for text in _texts() for line in _fenced(text) if _TEST_COMMAND.search(line)]
    assert runs, "the skill shows no test run at all"
    bare = [line for line in runs if not _NAMED_TARGET.search(line)]
    assert not bare, f"test runs without a named file or node id: {bare}"


def test_the_suite_run_belongs_to_the_developer() -> None:
    body = " ".join(skill_parts(_SKILL)[1].split()).lower()
    assert "name files or node ids, never a directory" in body, "no rule that a run names its files"
    assert "full-suite runs belong to the developer" in body, "the bare suite run survived the port"


def test_the_reference_is_linked_and_licensed() -> None:
    assert "(writing-good-tests.md)" in skill_parts(_SKILL)[1]
    assert (_FOLDER / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
