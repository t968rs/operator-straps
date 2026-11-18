"""Contract of the merge-commit-msg docs: the message travels on stdin, no working document stands between.

``merge_commit_msg.py capture`` prints the facts and ``build`` takes the message on stdin and writes only the
TXT, so neither the skill, its format card, the hook docstring nor the README may route work through a
``PR<N>_merge.md``. The squash mode is selected by ``--squash``, ``-s`` or a bare ``squash`` right after the
PR number; the docs name all three forms and both subjects. ``--auto-title`` or the ``auto_title`` key is the
only route to ``retitle``; the argument rule lists the title flags as accepted, apart from the rejection rule.
"""
from __future__ import annotations

from pathlib import Path

from conftest import PLUGIN_ROOT, REPO_ROOT
from harness_lib.skill_parts import skill_parts

NAME = "merge-commit-msg"
SKILL_DIR = PLUGIN_ROOT / "skills" / NAME
HINT = "<PR number> [squash | --squash | -s] [--auto-title] [--no-auto-title] [-- <guidance>]"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def test_frontmatter_names_the_skill_folder() -> None:
    assert skill_parts(SKILL_DIR / "SKILL.md")[0]["name"].strip("\"'") == NAME


def test_description_is_filled() -> None:
    description = skill_parts(SKILL_DIR / "SKILL.md")[0].get("description", "").strip("\"'")
    assert description.startswith("Use when"), description


def test_skill_and_format_card_name_no_working_md() -> None:
    for path in (SKILL_DIR / "SKILL.md", SKILL_DIR / "message_format.md"):
        assert "_merge.md" not in _text(path), path.name


def test_readme_and_guard_hook_name_no_working_md() -> None:
    for path in (REPO_ROOT / "README.md", PLUGIN_ROOT / "hooks" / "guard_commit_txt.py"):
        assert "_merge.md" not in _text(path), path.name


def test_skill_passes_the_message_to_build_on_stdin() -> None:
    text = _text(SKILL_DIR / "SKILL.md")
    assert "<<'MSG'" in text
    assert 'merge_commit_msg.py" build <PR number> <<' in text
    assert "\nMSG\n```" in text


def test_skill_has_two_steps_capture_then_build() -> None:
    text = _text(SKILL_DIR / "SKILL.md")
    assert "## Step 1" in text and "## Step 2" in text and "## Step 3" not in text


def test_skill_says_capture_pulls_the_diffs_and_bans_running_git_diff() -> None:
    text = _text(SKILL_DIR / "SKILL.md")
    assert "pulls the diffs" in text and "the printed Diff" in text
    assert "runs no `git diff`" in text
    assert "run `git diff`" not in text.lower()


def test_skill_names_the_change_route() -> None:
    text = _text(SKILL_DIR / "SKILL.md")
    assert "Changing a saved message" in text
    assert "changed as asked, on stdin" in text


def test_format_card_and_readme_name_the_stdin_route() -> None:
    for path in (SKILL_DIR / "message_format.md", REPO_ROOT / "README.md"):
        assert "stdin" in _text(path), path.name


def test_argument_hint_names_the_squash_forms() -> None:
    assert skill_parts(SKILL_DIR / "SKILL.md")[0].get("argument-hint", "").strip("\"'") == HINT


def test_skill_gates_retitle_on_the_auto_title_flag() -> None:
    text = _text(SKILL_DIR / "SKILL.md")
    assert "**`--auto-title`** is the developer's consent to rename the PR" in text
    assert 'merge_commit_msg.py" retitle <PR number> --title "<new title>"' in text
    assert "`retitle` or `gh pr edit` unasked" in _section(text, "## Common Mistakes")


def test_skill_names_the_auto_title_key_as_consent() -> None:
    text = _text(SKILL_DIR / "SKILL.md")
    assert '`"auto_title": true` in the project\'s `.claude/harness.json` is the same consent' in text
    assert "`--no-auto-title`, also only from the invocation, withdraws" in text


def test_argument_rule_accepts_the_title_flags_and_rejects_apart() -> None:
    text = _text(SKILL_DIR / "SKILL.md")
    rules = text.split("**Arguments for this run:**", 1)[1].split("\n\nOn every", 1)[0]
    accepted = rules.split("- Accepted before `--`:", 1)[1].split("\n- ", 1)[0]
    rejected = rules.split("- Rejected before `--`:", 1)[1].split("\n- ", 1)[0]
    assert "`--auto-title`" in accepted and "`--no-auto-title`" in accepted
    assert "auto-title" not in rejected and "beyond" not in rules


def test_description_triggers_on_a_squash_message() -> None:
    description = skill_parts(SKILL_DIR / "SKILL.md")[0].get("description", "")
    assert "squash message" in description, description


def test_skill_names_the_three_forms_and_keeps_squash_after_the_split_as_guidance() -> None:
    text = _text(SKILL_DIR / "SKILL.md")
    assert all(form in text for form in ("`--squash`", "`-s`", "`squash`"))
    assert "`squash` after `--` is guidance" in text


def test_skill_states_both_subjects() -> None:
    text = _text(SKILL_DIR / "SKILL.md")
    assert "`Merge PR #N -- <title>`" in text and "`<title> (#N)`" in text


def test_common_mistakes_cover_a_mode_mismatch() -> None:
    assert "--squash" in _section(_text(SKILL_DIR / "SKILL.md"), "## Common Mistakes")


def test_format_card_states_both_subjects_and_a_squash_example() -> None:
    text = _text(SKILL_DIR / "message_format.md")
    assert "Merge PR #NNN -- <title>" in text and "<title> (#NNN)" in text
    assert "## Worked example (squash" in text


def test_readme_and_rules_name_the_squash_mode() -> None:
    assert "/harness:merge-commit-msg 123 --squash" in _text(REPO_ROOT / "README.md")
    assert "squash mode" in _text(PLUGIN_ROOT / "rules" / "HARNESS_RULES.md")
