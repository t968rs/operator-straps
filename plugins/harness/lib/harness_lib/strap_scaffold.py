"""strap-skills: locate the target plugin, plan a skill's parts and render the shipped templates into it.

``find_plugin_dir`` finds the one plugin under the project whose manifest names it, so no plugin path is
hard-coded. ``planned_parts`` lists the files ``scaffold`` owns: ``SKILL.md`` and a contract test always, a
models and an API module when any behavior is mechanical, plus every part the author already listed.
``render_parts`` fills the templates under ``skills/strap-skills/templates/`` (read from the installed plugin)
with ``string.Template`` and writes the missing targets; every target is checked before any write, so a
refusal writes nothing. Requires an activated config.
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from string import Template
from typing import Dict, Iterator, List, Optional, Tuple

from harness_lib.config import active
from harness_lib.project import plugin_root
from harness_lib.strap_api import StrapError
from harness_lib.strap_models import BehaviorKind, Part, PartKind, SkillSpec, SpecMode

_MANIFEST = Path(".claude-plugin") / "plugin.json"
_SKIP_DIRS = frozenset({".git", "node_modules"})
_TEMPLATE_DIR = ("skills", "strap-skills", "templates")
# Spelled out so tools/select_tests.py ties each template file to this module.
_TEMPLATES: Dict[PartKind, str] = {
    PartKind.SKILL_MD: "skill_md.tmpl",
    PartKind.MODELS: "models.tmpl",
    PartKind.API: "api.tmpl",
    PartKind.CONTRACT_TEST: "contract_test.tmpl",
}
_DESCRIPTION_STUB = "TODO: Use when ..."


# --- plugin lookup --------------------------------------------------------------------------------------

def _pruned(path: Path) -> bool:
    """True for a directory the search never enters: hidden, skipped by name, or a linked worktree."""
    return path.name.startswith(".") or path.name in _SKIP_DIRS or (path / ".git").is_file()


def _directories(project: Path) -> Iterator[Path]:
    """``project`` and every directory below it that the search enters, in sorted walk order."""
    for top, dirs, _files in os.walk(project):
        base = Path(top)
        dirs[:] = sorted(entry for entry in dirs if not _pruned(base / entry))
        yield base


def _manifest_name(folder: Path) -> Optional[str]:
    """The ``name`` in ``folder``'s plugin manifest; None when there is none or it does not parse."""
    manifest = folder / _MANIFEST
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = data.get("name") if isinstance(data, dict) else None
    return name if isinstance(name, str) else None


def find_plugin_dir(project: Path, plugin_name: str) -> Path:
    """The one directory under ``project`` whose ``.claude-plugin/plugin.json`` is named ``plugin_name``."""
    found = [folder for folder in _directories(Path(project)) if _manifest_name(folder) == plugin_name]
    if not found:
        raise StrapError(f"no plugin named {plugin_name!r} under {Path(project).as_posix()}")
    if len(found) > 1:
        listed = ", ".join(folder.as_posix() for folder in found)
        raise StrapError(f"{len(found)} plugins named {plugin_name!r}: {listed}")
    return found[0]


# --- planned parts --------------------------------------------------------------------------------------

def _snake(name: str) -> str:
    return name.replace("-", "_")


def _contract_path(name: str) -> str:
    """Project-relative contract test path under the first configured test root."""
    roots = active().tests.roots
    if not roots:
        raise StrapError("tests.roots is empty, so the contract test has no root")
    return PurePosixPath(roots[0], "skills", f"test_{_snake(name)}_skill_contract.py").as_posix()


def _scaffold_parts(spec: SkillSpec) -> List[Part]:
    """The parts ``scaffold`` owns for ``spec``, each path project-relative POSIX."""
    snake = _snake(spec.name)

    def in_plugin(kind: PartKind, rel: str) -> Part:
        return Part(kind=kind, path=PurePosixPath(spec.plugin_dir, rel).as_posix())

    parts = [in_plugin(PartKind.SKILL_MD, f"skills/{spec.name}/SKILL.md")]
    if any(behavior.kind == BehaviorKind.MECHANICAL for behavior in spec.behaviors):
        parts.append(in_plugin(PartKind.MODELS, f"lib/harness_lib/{snake}_models.py"))
        parts.append(in_plugin(PartKind.API, f"lib/harness_lib/{snake}_api.py"))
    parts.append(Part(kind=PartKind.CONTRACT_TEST, path=_contract_path(spec.name)))
    return parts


def planned_parts(spec: SkillSpec) -> List[Part]:
    """``spec.parts`` as listed, then each scaffold-owned part whose path is not listed yet."""
    parts = list(spec.parts)
    listed = {part.path for part in parts}
    for part in _scaffold_parts(spec):
        if part.path not in listed:
            parts.append(part)
            listed.add(part.path)
    return parts


# --- rendering ------------------------------------------------------------------------------------------

def _substitutions(spec: SkillSpec) -> Dict[str, str]:
    return {"name": spec.name, "snake": _snake(spec.name), "title": spec.name.replace("-", " ").title(),
            "description": _DESCRIPTION_STUB}


def _template_text(kind: PartKind) -> str:
    return plugin_root().joinpath(*_TEMPLATE_DIR, _TEMPLATES[kind]).read_text(encoding="utf-8")


def _targets(spec: SkillSpec, project: Path) -> List[Tuple[PartKind, Path]]:
    """Each planned part that has a template, with its absolute target path."""
    kinds = ((PartKind(part.kind), part.path) for part in planned_parts(spec))
    return [(kind, Path(project) / rel) for kind, rel in kinds if kind in _TEMPLATES]


def render_parts(spec: SkillSpec, project: Path) -> List[Path]:
    """Write each templated planned part that is missing; a NEW spec with any target present writes none."""
    targets = _targets(spec, project)
    taken = [path for _kind, path in targets if path.exists()]
    if taken and SpecMode(spec.mode) == SpecMode.NEW:
        listed = ", ".join(path.as_posix() for path in taken)
        raise StrapError(f"{spec.name} is a new skill but these parts exist: {listed}")
    values = _substitutions(spec)
    rendered = [(path, Template(_template_text(kind)).substitute(values))
                for kind, path in targets if not path.exists()]
    for path, text in rendered:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return [path for path, _text in rendered]
