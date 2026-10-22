"""Guard test: the fold-in-review skill and README stay aligned with the driver's `fold` command.

The skill is prose over `pr_review.py fold` and the `Finding` model. The test pins the names the prose must
share with them: fold kinds, finding fields, fold flags, and the severity rule for a fold after `build`.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "harness"
_SKILL_DIR = _PLUGIN_ROOT / "skills" / "fold-in-review"
_SKILL = _SKILL_DIR / "SKILL.md"
_README = _SKILL_DIR / "README.md"
_DRIVER = _PLUGIN_ROOT / "scripts" / "pr_review.py"
_MODELS = _PLUGIN_ROOT / "lib" / "harness_lib" / "review_models.py"
_PR_REVIEW_SKILL = _PLUGIN_ROOT / "skills" / "pr-review" / "SKILL.md"

_FOLD_FLAGS = ("--pr", "--source", "--kind", "--from-gh-review", "--findings", "--severity")


def _text(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"missing {path}")
    return path.read_text(encoding="utf-8")


def _fold_kinds() -> List[str]:
    match = re.search(r"^FOLD_KINDS = \(([^)]*)\)", _text(_DRIVER), re.MULTILINE)
    assert match, "pr_review.py has no FOLD_KINDS tuple"
    return re.findall(r'"(\w+)"', match.group(1))


def _finding_fields() -> List[str]:
    parts = _text(_MODELS).split("class Finding(BaseModel):", 1)
    assert len(parts) == 2, "review_models.py has no class Finding(BaseModel)"
    body = re.split(r"^(?:class |    (?:def |class |@))", parts[1], maxsplit=1, flags=re.MULTILINE)[0]
    fields = re.findall(r"^    (\w+): ", body, re.MULTILINE)
    assert fields, "class Finding declares no fields before its first method"
    return fields


def test_frontmatter_names_the_skill_and_its_inputs() -> None:
    text = _text(_SKILL)
    assert re.search(r"^name: fold-in-review$", text, re.MULTILINE)
    hint = re.search(r"^argument-hint:\s*(.+)$", text, re.MULTILINE)
    assert hint, "SKILL.md has no argument-hint"
    for needle in ("notes", "test output", "URL"):
        assert needle in hint.group(1), f"argument-hint never mentions {needle!r}"
    assert "$ARGUMENTS" in text.split("---", 2)[2]


def test_every_driver_fold_kind_is_documented_in_skill_and_readme() -> None:
    kinds = _fold_kinds()
    assert kinds, "no fold kinds parsed"
    for path in (_SKILL, _README):
        text = _text(path)
        for kind in kinds:
            assert f"`{kind}`" in text, f"{path.name} never names the {kind!r} kind"


def test_finding_field_table_lists_every_model_field() -> None:
    fields = _finding_fields()
    assert {"severity", "file", "fix_kind"} <= set(fields), fields
    table = _text(_SKILL).split("**Write each finding**", 1)[1]
    for field in fields:
        assert f"| `{field}` |" in table, f"field table has no row for {field!r}"


def _fold_parser_body() -> str:
    """Source of ``_add_fold_command``; ``--pr`` comes from the ``_pr`` helper it wraps the parser in."""
    body = _text(_DRIVER).split("def _add_fold_command(", 1)
    assert len(body) == 2, "pr_review.py has no _add_fold_command"
    return body[1].split("\ndef ", 1)[0]


def _uses_flag(text: str, flag: str) -> bool:
    return re.search(rf"{re.escape(flag)}(?![\w-])", text) is not None


def test_fold_flags_exist_in_the_driver_and_are_used_by_the_skill() -> None:
    fold, skill = _fold_parser_body(), _text(_SKILL)
    assert "_pr(sub.add_parser(\"fold\"" in fold, "fold no longer takes --pr through _pr"
    for flag in _FOLD_FLAGS:
        if flag != "--pr":
            assert f'"{flag}"' in fold, f"the fold parser defines no {flag}"
        assert _uses_flag(skill, flag), f"SKILL.md never uses {flag}"
    assert "--findings -" in skill, "the stdin form is the documented default"
    assert "<<'EOF'" in skill


def test_post_build_severity_is_final_and_never_defaults_for_serious_defects() -> None:
    text = " ".join(_text(_SKILL).split())
    assert "the severity written is final" in text
    assert "never lands at the default `minor`" in text
    assert "per-finding `severity`" in text


def test_repo_flag_is_placed_before_the_subcommand() -> None:
    text = _text(_SKILL)
    assert "pr_review.py --repo DIR fold" in text
    readme = _text(_README)
    assert "pr_review.py --repo DIR fold" in readme, "README never shows the --repo placement"
    fold = _fold_parser_body()
    for flag in _FOLD_FLAGS:
        if flag != "--pr" and _uses_flag(readme, flag):
            assert f'"{flag}"' in fold, f"README uses {flag} but the fold parser defines no {flag}"


def test_readme_shows_the_three_invocation_shapes() -> None:
    text = _text(_README)
    assert '/fold-in-review "' in text
    assert '/fold-in-review """' in text
    assert "pullrequestreview-" in text


def test_pr_review_names_the_skill() -> None:
    assert "harness:fold-in-review" in _text(_PR_REVIEW_SKILL)
