"""Contract test for the arc-straps ``arc-help-pages`` skill: SKILL.md frontmatter, heredocs and procedure.

The skill's modules sit on the pytest ``pythonpath`` and are imported by bare name; their behavior is tested
under ``tests/arc/``. Pinned here: every heredoc runs through the launcher line arc-straps skills use and
calls only names its module binds, the apply heredocs dry-run before they write, and the procedure reads the
tool's code before a fragment states anything.
"""
from __future__ import annotations

import ast
import builtins
import re
from typing import Dict, List, Tuple

import pytest

import arc_help_pages_api
from conftest import REPO_ROOT

NAME = "arc-help-pages"
SKILL_DIR = REPO_ROOT / "plugins" / "arc-straps" / "skills" / "arc-help-pages"
SKILL = SKILL_DIR / "SKILL.md"
LAUNCHER = 'harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/'
MODULES = {"arc_help_pages_api": arc_help_pages_api}
HEREDOC = re.compile("^" + re.escape(LAUNCHER) + r"(\w+)\.py\"( <\w+>)? <<'PY'\n(.*?)\nPY$", re.DOTALL | re.M)
# fpm: is the consuming project's package prefix; the fragment markers are help:... (decision D3).
BANNED = ("$FPM_PY", "PYTHONPATH", "scripts/fpm", "fpm:", "floodplain", "smooth_simplify",
          "SmoothAndSimplifyPolygons")
Heredoc = Tuple[str, bool, str]


def _skill_parts() -> Tuple[Dict[str, str], str]:
    """SKILL.md split into its frontmatter keys (values unquoted) and its body."""
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md has no frontmatter"
    head, _, body = text[4:].partition("\n---\n")
    keys = {}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith(" "):
            keys[key.strip()] = value.strip().strip("\"'")
    return keys, body


def _heredocs() -> List[Heredoc]:
    """``(module stem, whether an argument follows the --file path, body)`` for every launcher heredoc."""
    return [(stem, bool(arg), code) for stem, arg, code in HEREDOC.findall(_skill_parts()[1])]


def _called_names(code: str) -> List[str]:
    return [node.func.id for node in ast.walk(ast.parse(code))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]


def _uses_name(code: str) -> bool:
    return any(isinstance(node, ast.Name) and node.id == "name" for node in ast.walk(ast.parse(code)))


def test_frontmatter_names_the_skill_folder() -> None:
    assert _skill_parts()[0]["name"] == NAME == SKILL_DIR.name


def test_description_says_when_to_use_it() -> None:
    description = _skill_parts()[0].get("description", "")
    assert description.startswith("Use when"), description
    assert "help page" in description, description


def test_every_heredoc_goes_through_the_launcher() -> None:
    body = _skill_parts()[1]
    found = _heredocs()
    assert found and len(found) == body.count("<<'PY'"), "a heredoc misses the launcher or column 0"
    assert {stem for stem, _, _ in found} == set(MODULES)


def test_an_argument_follows_the_file_path_exactly_when_name_is_read() -> None:
    wrong = [code for _, arg, code in _heredocs() if arg != _uses_name(code)]
    assert not wrong, wrong


def test_heredoc_calls_are_bound_names_or_builtins() -> None:
    unknown = [(stem, called) for stem, _, code in _heredocs() for called in _called_names(code)
               if called not in MODULES[stem].__all__ and not hasattr(builtins, called)]
    assert not unknown, unknown


def test_apply_heredocs_dry_run_then_apply() -> None:
    codes = [code.strip() for _, _, code in _heredocs() if "apply_help(" in code]
    assert codes == ['print("\\n".join(apply_help(name).lines))',
                     'print("\\n".join(apply_help(name, apply=True).lines))'], codes


@pytest.mark.parametrize("phrase", ["entry module", "params model", "validator", "check_help_page",
                                    "check_links", "arc-meta"],
                         ids=["entry", "params", "validator", "check_page", "check_links", "arc_meta"])
def test_the_procedure_names_its_sources_and_checks(phrase: str) -> None:
    assert phrase in " ".join(_skill_parts()[1].split())


def test_body_has_no_project_literal() -> None:
    body = _skill_parts()[1]
    assert not [term for term in BANNED if term in body]
