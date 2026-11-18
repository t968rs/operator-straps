"""Where a strap-skills spec's skill lives, per profile: the skill-file paths and rewrites the driver asks of
a spec. The template set stays with ``strap_scaffold``, which picks it by ``Profile.kind``.

A spec with ``plugin_dir`` is a **harness** skill: its SKILL.md sits under ``<plugin_dir>/skills/<name>/``,
its models and API modules under ``<plugin_dir>/lib/harness_lib/``, its driver under
``<plugin_dir>/scripts/`` and its role agents under ``<plugin_dir>/agents/``. A spec with ``target`` is a
**project** skill: everything sits in ``<skills_dir>/<name>/`` (modules and driver in its ``scripts/``), and
role agents in ``agents_dir``.

``profile_of`` answers for an existing spec; ``new_fields`` picks the fields ``strap.py new`` stores, from the
configured ``strap.target``. Paths are project-relative POSIX strings.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional

from harness_lib.strap_models import SkillSpec, SkillTarget

PLUGIN_NAME = "harness"
PLUGIN_VAR = "${CLAUDE_PLUGIN_ROOT}"
SKILL_DIR_VAR = "${CLAUDE_SKILL_DIR}"
PROJECT_DIR_VAR = "${CLAUDE_PROJECT_DIR}"
HARNESS = "harness"
PROJECT = "project"


def _join(*parts: str) -> str:
    return PurePosixPath(*parts).as_posix()


def snake_case(name: str) -> str:
    """``name`` with hyphens as underscores: the stem of the skill's module and test file names."""
    return name.replace("-", "_")


@dataclass(frozen=True)
class Profile:
    """The answers for one spec; ``plugin_dir`` is None for a project skill."""

    kind: str
    skill_folder: str
    skill_md: str
    models: str
    api: str
    driver: str
    agents_dir: str
    bump: Optional[str]
    plugin_dir: Optional[str] = None

    def rewrite(self, text: str, source: Path, run_tree: Path) -> str:
        """``text`` with the skill variables pointing at ``source`` (and, for a project skill,
        ``${CLAUDE_PROJECT_DIR}`` at ``run_tree``, where a scenario's writes must land)."""
        text = text.replace(SKILL_DIR_VAR, (Path(source) / self.skill_folder).as_posix())
        if self.plugin_dir is not None:
            return text.replace(PLUGIN_VAR, (Path(source) / self.plugin_dir).as_posix())
        return text.replace(PROJECT_DIR_VAR, Path(run_tree).as_posix())


def _harness(name: str, plugin_dir: str) -> Profile:
    snake = snake_case(name)
    folder = _join(plugin_dir, "skills", name)
    return Profile(kind=HARNESS, skill_folder=folder, skill_md=_join(folder, "SKILL.md"),
                   models=_join(plugin_dir, "lib", "harness_lib", f"{snake}_models.py"),
                   api=_join(plugin_dir, "lib", "harness_lib", f"{snake}_api.py"),
                   driver=_join(plugin_dir, "scripts", f"{snake}.py"),
                   agents_dir=_join(plugin_dir, "agents"),
                   bump=_join(plugin_dir, ".claude-plugin", "plugin.json"),
                   plugin_dir=plugin_dir)


def _project(name: str, target: SkillTarget) -> Profile:
    snake = snake_case(name)
    folder = _join(target.skills_dir, name)
    return Profile(kind=PROJECT, skill_folder=folder, skill_md=_join(folder, "SKILL.md"),
                   models=_join(folder, "scripts", f"{snake}_models.py"),
                   api=_join(folder, "scripts", f"{snake}_api.py"),
                   driver=_join(folder, "scripts", f"{snake}.py"),
                   agents_dir=PurePosixPath(target.agents_dir).as_posix(), bump=None)


def profile_of(spec: SkillSpec) -> Profile:
    """The profile of ``spec``: harness when it carries ``plugin_dir``, project when it carries ``target``."""
    if spec.target is not None:
        return _project(spec.name, spec.target)
    assert spec.plugin_dir is not None, "SkillSpec validates exactly one of plugin_dir and target"
    return _harness(spec.name, spec.plugin_dir)


def _folder(value: str) -> str:
    """A configured folder in canonical POSIX form (backslashes, ``./`` and a trailing slash folded), so the
    recorded form never depends on how ``harness.json`` spells it."""
    return PurePosixPath(value.replace("\\", "/")).as_posix()


def _project_rel(found: Path, root: Path) -> str:
    """``found`` relative to ``root`` in POSIX form; its absolute form when it resolves outside ``root`` (a
    linked plugin folder), as the driver's own path display does."""
    try:
        return Path(found).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(found).as_posix()


def new_fields(cfg: Any, root: Path) -> Dict[str, Any]:
    """The ``SkillSpec`` fields ``strap.py new`` stores for the configured ``strap.target``: ``plugin_dir`` of
    the project's ``harness`` plugin, or a ``target`` built from ``skills_dir`` and ``agents_dir``."""
    if cfg.strap.target == HARNESS:
        from harness_lib.strap_scaffold import find_plugin_dir  # strap_scaffold imports this module
        return {"plugin_dir": _project_rel(find_plugin_dir(root, PLUGIN_NAME), root)}
    return {"target": SkillTarget(skills_dir=_folder(cfg.skills_dir), agents_dir=_folder(cfg.agents_dir))}
