"""Behavioral tests for the per-skill-package trigger over any ``skills/`` folder (pure planning half).

A skill folder is ``<prefix>skills/<name>/`` holding a ``SKILL.md`` at the PR head, wherever it sits: the
project's ``skills_dir`` no longer limits the trigger. The cross-reference search runs over ``.claude``,
``docs``, ``.github`` and the top folder of each skill root, and a hit inside the skill's own folder never
counts.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harness_lib import review_plan as rp
from harness_lib.config import activate, load_config

_PATTERNS = ("docs/PR_REVIEWS/*_*.json",)


@pytest.fixture(autouse=True)
def project(make_project) -> Path:
    """A project whose ``skills_dir`` (``agents/skills/``) holds no candidate skill folder below."""
    root = make_project(config={"exclusions": None, "skills_dir": "agents/skills/"})
    activate(load_config(root))
    return root


class TestCandidates:
    """Every ``skills/<name>/`` folder a path sits under is a candidate; ``skills_dir`` plays no part."""

    def test_candidates_sorted_unique(self) -> None:
        paths = ["plugins/harness/skills/pr-review/SKILL.md", "plugins/harness/skills/pr-review/a/b.json",
                 ".claude/skills/porting/notes.md", "src/skills/fake/x.py", "tests/skills/test_a.py",
                 "agents/skills/README.md", "docs/a.md"]
        assert rp.skill_candidates(paths) == (".claude/skills/porting/", "plugins/harness/skills/pr-review/",
                                              "src/skills/fake/")

    def test_skill_files_name_each_candidate_skill_md(self) -> None:
        assert rp.skill_files(("a/skills/x/", "skills/y/")) == ("a/skills/x/SKILL.md", "skills/y/SKILL.md")

    def test_only_folders_holding_skill_md_count(self) -> None:
        candidates = (".claude/skills/porting/", "plugins/harness/skills/pr-review/", "src/skills/fake/")
        present = ["plugins/harness/skills/pr-review/SKILL.md", ".claude/skills/porting/SKILL.md",
                   "src/skills/fake/x.py"]
        assert rp.skill_folders(candidates, present) == candidates[:2]

    def test_skill_name_is_the_folder_name(self) -> None:
        assert rp.skill_name("plugins/harness/skills/pr-review/") == "pr-review"


class TestGrepRoots:
    """The search covers the fixed roots plus each skill root's top folder, once each, in order."""

    def test_roots(self) -> None:
        folders = ("plugins/harness/skills/a/", ".claude/skills/b/", "plugins/arc/skills/c/")
        assert rp.skill_grep_roots(folders) == (".claude", "docs", ".github", "plugins")


class TestMentioned:
    """A whole-name hit outside the skill's own folder fires; excluded paths never count."""

    def test_hit_outside_folder_fires(self) -> None:
        assert rp.skill_mentioned("plugins/h/skills/pr-sum/", ["docs/a.md:3:run pr-sum"], _PATTERNS)

    def test_hit_in_another_root_counts(self) -> None:
        lines = [".claude/skills/pr-sum/SKILL.md:1:name: pr-sum"]
        assert rp.skill_mentioned("plugins/h/skills/pr-sum/", lines, _PATTERNS)

    def test_hit_inside_own_folder_does_not(self) -> None:
        lines = ["plugins/h/skills/pr-sum/SKILL.md:1:name: pr-sum"]
        assert not rp.skill_mentioned("plugins/h/skills/pr-sum/", lines, _PATTERNS)
        assert rp.skill_mentioned("plugins/h/skills/pr-sum/", [*lines, "docs/a.md:2:pr-sum"], _PATTERNS)

    def test_longer_name_and_excluded_path_do_not(self) -> None:
        lines = ["docs/a.md:1:see pr-sum-watch", "docs/PR_REVIEWS/12_x.json:2:pr-sum"]
        assert not rp.skill_mentioned("plugins/h/skills/pr-sum/", lines, _PATTERNS)
        assert rp.skill_mentioned("plugins/h/skills/pr-sum/", [*lines, "CLAUDE.md:3:pr-sum"], _PATTERNS)


class TestOldHelpersRemoved:
    """The ``skills_dir``-bound helpers are gone from the planner."""

    def test_name_is_gone(self) -> None:
        assert [name for name in ("skills_dir", "skill_folder", "skills_touched") if hasattr(rp, name)] == []
