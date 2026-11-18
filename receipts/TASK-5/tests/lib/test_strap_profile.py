"""``strap_profile.profile_of``: every path and rewrite the driver asks of a spec, per profile.

The harness profile answers with today's paths; the project profile puts the models, API and driver in the
skill folder's ``scripts/``, reads agents from the configured agents folder and rewrites
``${CLAUDE_PROJECT_DIR}`` to the run tree.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from harness_lib.strap_models import SkillSpec, SkillTarget, SpecMode
from harness_lib.strap_profile import new_fields, profile_of

NAME = "demo-skill"


def _harness() -> SkillSpec:
    return SkillSpec(name=NAME, mode=SpecMode.NEW, plugin_dir="plugins/harness")


def _project() -> SkillSpec:
    target = SkillTarget(skills_dir=".claude/skills", agents_dir=".claude/agents")
    return SkillSpec(name=NAME, mode=SpecMode.NEW, target=target)


def test_harness_profile_keeps_todays_paths() -> None:
    profile = profile_of(_harness())
    assert profile.skill_folder == "plugins/harness/skills/demo-skill"
    assert profile.skill_md == "plugins/harness/skills/demo-skill/SKILL.md"
    assert profile.models == "plugins/harness/lib/harness_lib/demo_skill_models.py"
    assert profile.api == "plugins/harness/lib/harness_lib/demo_skill_api.py"
    assert profile.driver == "plugins/harness/scripts/demo_skill.py"
    assert profile.agents_dir == "plugins/harness/agents"
    assert profile.bump == "plugins/harness/.claude-plugin/plugin.json"


def test_project_profile_puts_modules_in_the_skill_folder() -> None:
    profile = profile_of(_project())
    assert profile.skill_folder == ".claude/skills/demo-skill"
    assert profile.skill_md == ".claude/skills/demo-skill/SKILL.md"
    assert profile.models == ".claude/skills/demo-skill/scripts/demo_skill_models.py"
    assert profile.api == ".claude/skills/demo-skill/scripts/demo_skill_api.py"
    assert profile.driver == ".claude/skills/demo-skill/scripts/demo_skill.py"
    assert profile.agents_dir == ".claude/agents"
    assert profile.bump is None


def test_harness_rewrite_matches_today(tmp_path: Path) -> None:
    source, tree = tmp_path / "source", tmp_path / "tree"
    text = "${CLAUDE_PLUGIN_ROOT}/scripts/x.py ${CLAUDE_SKILL_DIR}/y.md ${CLAUDE_PROJECT_DIR}/z"
    expected = (f"{source.as_posix()}/plugins/harness/scripts/x.py "
                f"{source.as_posix()}/plugins/harness/skills/demo-skill/y.md ${{CLAUDE_PROJECT_DIR}}/z")
    assert profile_of(_harness()).rewrite(text, source, tree) == expected


def test_project_rewrite_points_project_dir_at_the_run_tree(tmp_path: Path) -> None:
    source, tree = tmp_path / "source", tmp_path / "tree"
    text = "${CLAUDE_SKILL_DIR}/scripts/a.py ${CLAUDE_PROJECT_DIR}/docs ${CLAUDE_PLUGIN_ROOT}/x"
    expected = (f"{source.as_posix()}/.claude/skills/demo-skill/scripts/a.py "
                f"{tree.as_posix()}/docs ${{CLAUDE_PLUGIN_ROOT}}/x")
    assert profile_of(_project()).rewrite(text, source, tree) == expected


def test_new_fields_records_canonical_project_folders(tmp_path: Path) -> None:
    cfg = SimpleNamespace(strap=SimpleNamespace(target="project"), skills_dir="./.claude/skills/",
                          agents_dir=r".claude\agents" + "\\")
    assert new_fields(cfg, tmp_path) == {
        "target": SkillTarget(skills_dir=".claude/skills", agents_dir=".claude/agents")}
