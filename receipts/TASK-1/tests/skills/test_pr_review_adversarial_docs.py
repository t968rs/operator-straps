"""The review skills document ``-a`` / ``--adversarial``.

pr-review: the argument hint and the capture row name the flag; the Workflow dispatch names ``scriptPath``
and the one ``args.guidance`` exception to the no-edit rule; ``refute`` and ``unrefute`` subcommand rows (no
``amend --unrefute``); the Model floor covers the refuter; the worst-case agent count. operating_rules
defines REFUTED, BUBBLED and NOT_RESOLVED and names ``refute`` and ``unrefute --bubble`` / ``--fix``.
review-local takes the flag (hint, capture line, an "Under -a" paragraph).
fold-in-review says folded findings are not refuted. The flag is pr-review's, not pr-team's. The schemas
README names the current schema version and REFUTED, the harness plugin is at least 0.71.0 and a release note
names ``--adversarial``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from conftest import REPO_ROOT
from harness_lib import review_merge as rmg

WALK_ROOTS = ("docs/RELEASES/",)
_HARNESS = REPO_ROOT / "plugins" / "harness"
_SKILLS = _HARNESS / "skills"
_FLAG = re.compile(r"(?<![\w-])(-a|--adversarial)(?![\w-])")


def _read(*parts: str) -> str:
    return _SKILLS.joinpath(*parts).read_text(encoding="utf-8")


def _hint(text: str) -> str:
    return next((line for line in text.split("---")[1].splitlines() if line.startswith("argument-hint:")), "")


def _section(text: str, heading: str) -> str:
    """The body under ``heading`` up to the next heading of any level."""
    start = text.index(heading) + len(heading)
    nxt = re.search(r"^#{1,6} ", text[start:], re.M)
    return text[start:start + nxt.start()] if nxt else text[start:]


def _table_rows(text: str, command: str) -> List[str]:
    return [line for line in text.splitlines() if line.startswith(f"| `{command}")]


def test_pr_review_argument_hint_names_the_flag() -> None:
    assert _FLAG.search(_hint(_read("pr-review", "SKILL.md")))


def test_pr_review_capture_row_names_the_flag() -> None:
    rows = _table_rows(_read("pr-review", "SKILL.md"), "capture")
    assert rows and any(_FLAG.search(row) for row in rows), rows


def test_pr_review_dispatches_a_workflow_with_a_script_path() -> None:
    text = _read("pr-review", "SKILL.md")
    assert re.search(r"\bWorkflow\b", text) and "scriptPath" in text


def test_pr_review_names_the_guidance_exception() -> None:
    assert "args.guidance" in _read("pr-review", "SKILL.md")


def test_pr_review_lists_refute_and_unrefute_subcommands_not_an_amend_flag() -> None:
    text = _read("pr-review", "SKILL.md")
    refute = [line for line in text.splitlines() if re.match(r"\| `refute[ `]", line)]
    unrefute = [line for line in text.splitlines() if re.match(r"\| `unrefute[ `]", line)]
    assert refute and unrefute
    assert any("--bubble" in row and "--fix" in row for row in unrefute), unrefute
    assert "amend --unrefute" not in text
    assert not any("--unrefute" in row for row in _table_rows(text, "amend"))


def test_pr_review_model_floor_covers_the_refuter() -> None:
    floor = _section(_read("pr-review", "SKILL.md"), "### Model floor")
    assert "refuter" in floor.lower() and "opus" in floor


def test_pr_review_states_the_worst_case_agent_count() -> None:
    assert re.search(r"2\s*\(\s*R\s*\+\s*C\s*\)", _read("pr-review", "SKILL.md"))


def test_operating_rules_define_the_three_new_statuses() -> None:
    text = _read("pr-review", "operating_rules.md")
    for status in ("REFUTED", "BUBBLED", "NOT_RESOLVED"):
        assert re.search(rf"\b{status}\b", text), status
    assert "UNREFUTED" not in text


def test_operating_rules_name_the_overrule_commands() -> None:
    text = _read("pr-review", "operating_rules.md")
    assert re.search(r"(?<![\w-])refute\b", text)
    assert re.search(r"\bunrefute --bubble\b", text) and re.search(r"\bunrefute --fix\b", text)


def test_review_local_argument_hint_names_the_flag() -> None:
    assert _FLAG.search(_hint(_read("review-local", "SKILL.md")))


def test_review_local_capture_line_carries_the_flag() -> None:
    lines = [line for line in _read("review-local", "SKILL.md").splitlines()
             if "pr_review.py" in line and "capture --range" in line]
    assert lines and any(_FLAG.search(line) for line in lines), lines


def test_review_local_has_an_under_a_paragraph() -> None:
    assert re.search(r"Under `?-a`?", _read("review-local", "SKILL.md"))


def test_fold_in_review_says_folded_findings_are_not_refuted() -> None:
    assert re.search(r"(?i)\bnot refuted\b", _read("fold-in-review", "SKILL.md"))


def test_the_flag_is_pr_reviews_not_pr_teams() -> None:
    assert "--adversarial" in _read("pr-review", "SKILL.md")
    # D2-scoped: pr-team takes no -a on this branch; these two checks drop with the plan of TASK-8's TODO.
    assert not _FLAG.search(_hint(_read("pr-team", "SKILL.md")))
    assert "--adversarial" not in _read("pr-team", "SKILL.md")


def test_schemas_readme_names_the_new_version() -> None:
    text = (_HARNESS / "schemas" / "README.md").read_text(encoding="utf-8")
    assert f'currently "{rmg.SCHEMA_VERSION}"' in text and "REFUTED" in text


def test_harness_plugin_version_is_bumped() -> None:
    manifest = json.loads((_HARNESS / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert tuple(int(part) for part in manifest["version"].split(".")) >= (0, 71, 0), manifest["version"]


def test_a_release_note_names_the_flag() -> None:
    notes: List[Path] = sorted((REPO_ROOT / "docs" / "RELEASES").glob("v*.md"))
    assert any("--adversarial" in p.read_text(encoding="utf-8") for p in notes)
