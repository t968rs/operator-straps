"""Contract test for the arc-straps ``arc-meta`` skill: its SKILL.md frontmatter, heredocs, rules and models.

The skill's modules sit on the pytest ``pythonpath`` and are imported by bare name; their behavior is tested
under ``tests/arc/``, never copied. The literals pinned here are external contracts: the canonical XML
spellings of ParamType and Direction, the launcher line every heredoc uses, and three rule sentences that
carry the skill's judgment behavior verbatim from the source skill.
"""
from __future__ import annotations

import ast
import builtins
import re
from typing import Dict, List, Tuple

import pytest
from pydantic import ValidationError

import arc_meta_api
import arc_meta_models
import arc_meta_page
import arc_meta_rc
import arc_meta_toolbox
from conftest import REPO_ROOT

NAME = "arc-meta"
SKILL_DIR = REPO_ROOT / "plugins" / "arc-straps" / "skills" / "arc-meta"
SKILL = SKILL_DIR / "SKILL.md"
LAUNCHER = 'harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" --file "${CLAUDE_SKILL_DIR}/scripts/'
MODULES = {"arc_meta_api": arc_meta_api, "arc_meta_rc": arc_meta_rc, "arc_meta_page": arc_meta_page,
           "arc_meta_toolbox": arc_meta_toolbox}
HEREDOC = re.compile("^" + re.escape(LAUNCHER) + r"(\w+)\.py\"( <Tool>)? <<'PY'\n(.*?)\nPY$",
                     re.DOTALL | re.M)
Heredoc = Tuple[str, bool, str]
BANNED = ("$FPM_PY", "PYTHONPATH", "scripts/fpm", "patch_tool_rc.py", "clean_tool_metadata.py",
          "patch_toolbox_metadata.py", "metadata_format.py", "floodplain")
ARCHIVE_NAME = re.compile(r"[\w-]\.atbx\b")

B5_RULE = ("**Existing help text is a claim, not a source.** Every sentence in the canonical XML, the rc "
           "file or an old help page is re-derived from the entry module, the params model and the validator "
           "before it is kept, reworded or shortened.")
B8_LEAD = "**Written is not applied.**"
B8_ANSWER = ("When the developer asks whether a change is ready, shows, or \"uses the new X now\", apply it "
             "(Steps 4 and 5) and answer from `check_applied`, never from the generator's tests or a "
             "dry-run.")


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
    """``(module stem, whether <Tool> follows the --file path, body)`` for every launcher heredoc in the
    SKILL.md body whose launcher line and closing ``PY`` both start at column 0."""
    return [(stem, bool(tool), code) for stem, tool, code in HEREDOC.findall(_skill_parts()[1])]


def _uses_name(code: str) -> bool:
    """Whether ``code`` reads the bound ``name``."""
    return any(isinstance(node, ast.Name) and node.id == "name" for node in ast.walk(ast.parse(code)))


def _called_names(code: str) -> List[str]:
    """Every bare identifier called in ``code``."""
    return [node.func.id for node in ast.walk(ast.parse(code))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]


def test_frontmatter_names_the_skill_folder() -> None:
    assert _skill_parts()[0]["name"] == NAME == SKILL_DIR.name


def test_description_names_the_toolbox_help_without_a_project() -> None:
    description = _skill_parts()[0].get("description", "")
    assert description.startswith("Use when"), description
    assert "ArcGIS Pro" in description and ".atbx" in description, description
    assert not ARCHIVE_NAME.search(description), description


def test_api_heredoc_launches_the_skill_api() -> None:
    assert LAUNCHER + 'arc_meta_api.py"' in _skill_parts()[1]


def test_every_heredoc_goes_through_the_launcher() -> None:
    body = _skill_parts()[1]
    found = _heredocs()
    assert found and len(found) == body.count("<<'PY'"), "a heredoc misses the launcher or column 0"
    assert {stem for stem, _, _ in found} == set(MODULES)


def test_tool_argument_follows_the_file_path_exactly_when_name_is_read() -> None:
    wrong = [(stem, code) for stem, tool, code in _heredocs()
             if tool != _uses_name(code) or (stem == "arc_meta_toolbox" and tool)]
    assert not wrong, wrong


@pytest.mark.parametrize("stem", sorted(MODULES))
def test_heredoc_module_exists_and_exports_its_names(stem: str) -> None:
    module = MODULES[stem]
    assert (SKILL_DIR / "scripts" / f"{stem}.py").is_file()
    missing = [name for name in module.__all__ if not hasattr(module, name)]
    assert not missing, missing


def test_heredoc_calls_are_bound_names_or_builtins() -> None:
    unknown = [(stem, called) for stem, _, code in _heredocs() for called in _called_names(code)
               if called not in MODULES[stem].__all__ and not hasattr(builtins, called)]
    assert not unknown, unknown


APPLY_CALLS = {
    "arc_meta_rc": ("apply_rc(name)", "apply_rc(name, apply=True)"),
    "arc_meta_page": ("apply_page(name)", "apply_page(name, apply=True)"),
    "arc_meta_toolbox": ("apply_toolbox()", "apply_toolbox(apply=True)"),
}


@pytest.mark.parametrize("stem", sorted(APPLY_CALLS))
def test_apply_heredocs_dry_run_then_apply(stem: str) -> None:
    codes = [code.strip() for found, _, code in _heredocs() if found == stem]
    wanted = [rf'print("\n".join({call}.lines))' for call in APPLY_CALLS[stem]]
    assert codes == wanted, codes


def test_body_has_no_project_launcher_or_archive_literal() -> None:
    body = _skill_parts()[1]
    found = [term for term in BANNED if term in body]
    assert not found, found
    assert not ARCHIVE_NAME.findall(body), ARCHIVE_NAME.findall(body)


@pytest.mark.parametrize("sentence", [B5_RULE, B8_LEAD, B8_ANSWER], ids=["B5", "B8-lead", "B8-answer"])
def test_pinned_rule_sentences_appear_verbatim(sentence: str) -> None:
    assert " ".join(sentence.split()) in " ".join(_skill_parts()[1].split())


def test_api_exports_existing_names() -> None:
    missing = [name for name in arc_meta_api.__all__ if not hasattr(arc_meta_api, name)]
    assert not missing, missing


_VALID_PAYLOADS = {
    "ParamRow": {"name": "Mode", "title": "Mode", "type": "Required", "direction": "Input",
                 "datatype": "GPString", "hover_wired": False},
    "Problem": {"code": "page_stale", "tool": "Demo", "detail": "x"},
    "ToolSources": {"tool": "Demo"},
}


@pytest.mark.parametrize("model_name", sorted(_VALID_PAYLOADS))
def test_models_forbid_extra_keys(model_name: str) -> None:
    payload = _VALID_PAYLOADS[model_name]
    model = getattr(arc_meta_models, model_name)
    model.model_validate(payload)
    with pytest.raises(ValidationError):
        model.model_validate({**payload, "unexpected": 1})


def test_models_are_frozen() -> None:
    problem = arc_meta_models.Problem(code=arc_meta_models.ProblemCode.PAGE_STALE, tool="Demo", detail="x")
    with pytest.raises(ValidationError):
        problem.tool = "Other"


def test_problem_round_trips_through_its_dump() -> None:
    models = arc_meta_models
    problem = models.Problem(code=models.ProblemCode.HOVER_UNWIRED, tool="Demo", param="Mode",
                             detail="no ref")
    assert models.Problem.model_validate_json(problem.model_dump_json()) == problem


def test_param_row_spells_type_and_direction_like_the_canonical_xml() -> None:
    assert [t.value for t in arc_meta_models.ParamType] == ["Required", "Optional", "Derived"]
    assert [d.value for d in arc_meta_models.Direction] == ["Input", "Output"]


def test_api_records_are_the_models_module_classes() -> None:
    assert (arc_meta_api.ParamRow, arc_meta_api.ProblemCode) == (arc_meta_models.ParamRow,
                                                                  arc_meta_models.ProblemCode)
