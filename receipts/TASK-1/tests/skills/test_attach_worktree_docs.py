"""The a-w, d-w and harness-rules texts describe the dirty-target attach and its resolution loop."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_history_rule_names_the_attach_exception(plugin_root: Path) -> None:
    rules = _text(plugin_root / "rules" / "HARNESS_RULES.md")
    assert "attach_worktree.py" in rules
    assert "--continue" in rules and "--abort" in rules


def test_the_a_w_skill_describes_the_resolution_loop(plugin_root: Path) -> None:
    skill = _text(plugin_root / "skills" / "a-w" / "SKILL.md")
    for token in ("--continue", "--abort", "--auto-resolve", "attach.auto_resolve", "backup", "ambiguous"):
        assert token in skill, token
    assert "reset --hard" not in skill
    assert "no tracked changes" not in skill


def test_the_a_w_argument_hint_lists_the_new_flags(plugin_root: Path) -> None:
    skill = _text(plugin_root / "skills" / "a-w" / "SKILL.md")
    hint = next(line for line in skill.splitlines() if line.startswith("argument-hint:"))
    for flag in ("--auto-resolve", "--continue", "--abort"):
        assert flag in hint, flag


def test_the_d_w_skill_no_longer_sends_a_conflict_to_the_target(plugin_root: Path) -> None:
    skill = _text(plugin_root / "skills" / "d-w" / "SKILL.md")
    assert "markers in the target" not in skill
    assert "rebase" in skill and "--continue" in skill


def test_the_readme_a_w_row_drops_the_clean_target_requirement() -> None:
    readme = _text(REPO_ROOT / "README.md")
    row = next(line for line in readme.splitlines() if line.startswith("| (Re)Attach Worktree"))
    assert "no tracked changes" not in row
    assert "leaves markers" not in row
    assert "--continue" in row
