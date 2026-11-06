"""Contract of the merge-commit-msg docs: the message travels on stdin, no working document stands between.

``merge_commit_msg.py capture`` prints the facts and ``build`` takes the message on stdin and writes only the
TXT, so neither the skill, its format card, the hook docstring nor the README may route work through a
``PR<N>_merge.md``. The squash mode is selected by ``--squash``, ``-s`` or a bare ``squash`` right after the
PR number; the docs name all three forms and both subjects.
"""
from __future__ import annotations

from pathlib import Path

from conftest import PLUGIN_ROOT, REPO_ROOT
from harness_lib.skill_parts import skill_parts

NAME = "merge-commit-msg"
SKILL_DIR = PLUGIN_ROOT / "skills" / NAME
HINT = "<PR number> [squash | --squash | -s] [-- <guidance>]"


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
