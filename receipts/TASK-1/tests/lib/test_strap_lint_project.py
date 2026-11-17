"""``strap_lint.lint_project_skill``: the generic rule set for a project skill.

The generic rules (frontmatter, folder name, ``Use when`` description within the cap, no first or second
person, ``${CLAUDE_SKILL_DIR}`` paths that exist) apply; the harness house rules (argument pointer, hpy-only
fences, vendor names, ``harness:`` agents, ``harness_lib`` modules) do not.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from harness_lib.strap_lint import lint_project_skill

NAME = "demo-skill"
API_REF = "${CLAUDE_SKILL_DIR}/scripts/demo_skill_api.py"
CLEAN_BODY = (
    "Arguments: `$ARGUMENTS`\n\n"
    "Ask Claude to run the API; harness:no-such-agent and harness_lib.no_such_module are only named here.\n\n"
    "```\n"
    f'python tools/report.py\nharness-skill-api --file "{API_REF}" <name> <<\'PY\'\nPY\n'
    "```\n"
)


def _skill(tmp_path: Path, description: str, body: str = CLEAN_BODY, name: str = NAME,
           with_api: bool = True) -> Path:
    folder = tmp_path / ".claude" / "skills" / NAME
    folder.mkdir(parents=True)
    text = f"---\nname: {name}\ndescription: {description}\nargument-hint: \"<name>\"\n---\n\n{body}"
    (folder / "SKILL.md").write_text(text, encoding="utf-8", newline="\n")
    if with_api:
        (folder / "scripts").mkdir()
        (folder / "scripts" / "demo_skill_api.py").write_text("__all__ = []\n", encoding="utf-8")
    return folder


def _lint(folder: Path) -> List[str]:
    return lint_project_skill(folder, NAME)


def test_clean_project_skill_skips_the_harness_house_rules(tmp_path: Path) -> None:
    assert _lint(_skill(tmp_path, "Use when a ledger needs its total checked.")) == []


def test_description_rules_still_apply(tmp_path: Path) -> None:
    problems = _lint(_skill(tmp_path, "Checks your ledger total."))
    assert any("does not start with 'Use when'" in line for line in problems), problems
    assert any("first or second person" in line for line in problems), problems


def test_folder_name_must_match(tmp_path: Path) -> None:
    problems = _lint(_skill(tmp_path, "Use when a ledger needs a total.", name="other-skill"))
    assert any("does not match the folder name" in line for line in problems), problems


def test_missing_skill_dir_path_is_a_problem(tmp_path: Path) -> None:
    problems = _lint(_skill(tmp_path, "Use when a ledger needs a total.", with_api=False))
    assert any(API_REF in line and "does not exist" in line for line in problems), problems


def test_every_problem_is_prefixed_with_the_skill_name(tmp_path: Path) -> None:
    problems = _lint(_skill(tmp_path, "Checks your ledger total.", with_api=False))
    assert problems and all(line.startswith(f"{NAME}: ") for line in problems), problems
