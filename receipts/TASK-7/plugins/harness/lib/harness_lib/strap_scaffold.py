"""strap-skills: locate the target plugin, plan a skill's parts and render the shipped templates into it.

``find_plugin_dir`` finds the one plugin under the project whose manifest names it, so no plugin path is
hard-coded. ``planned_parts`` lists the files ``scaffold`` owns: ``SKILL.md`` and a contract test always, a
models and an API module when any behavior is mechanical (in an edit, only when the module exists; an
author who wants a new one lists it with ``add_part``), plus every part the author already listed. Where each
part goes comes from the spec's profile (``strap_profile``): a harness skill's plugin layout, or a project
skill's folder. ``render_parts`` fills the profile's templates (``skills/strap-skills/templates/``, or its
``project/`` folder; read from the installed plugin) with ``string.Template`` and writes the missing targets;
every target is checked before any write, so a refusal writes nothing. Requires an activated config.
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from string import Template
from typing import Dict, Iterator, List, Optional, Set, Tuple

from harness_lib.config import active
from harness_lib.project import plugin_root
from harness_lib.strap_api import StrapError
from harness_lib.strap_models import BehaviorKind, Part, PartKind, SkillSpec, SpecMode
from harness_lib.strap_profile import PROJECT, profile_of, snake_case

_MANIFEST = Path(".claude-plugin") / "plugin.json"
_SKIP_DIRS = frozenset({".git", "node_modules"})
# Spelled out so tools/select_tests.py ties each template file to this module: the folder literal is the
# anchor the harness set's names need once the project set shares them.
_TEMPLATE_DIR = ("skills", "strap-skills", "templates")
_TEMPLATES: Dict[PartKind, str] = {
    PartKind.SKILL_MD: "skill_md.tmpl",
    PartKind.MODELS: "models.tmpl",
    PartKind.API: "api.tmpl",
    PartKind.CONTRACT_TEST: "contract_test.tmpl",
}
# The project profile's set, each spelled with its "project/" folder for the same reason.
_PROJECT_TEMPLATES: Dict[PartKind, str] = {
    PartKind.SKILL_MD: "project/skill_md.tmpl",
    PartKind.MODELS: "project/models.tmpl",
    PartKind.API: "project/api.tmpl",
    PartKind.CONTRACT_TEST: "project/contract_test.tmpl",
}
_PROJECT_API_SECTION = "project/api_section.tmpl"
_NO_API_SECTION = ("## API\n\nTODO(fill): this skill has no API module yet. To add one, add a mechanical "
                   "behavior, list the models and API modules with add_part, and copy the heredoc from the "
                   "strap-skills project api_section template; or delete this section.\n\n")
# The project SKILL.md's API-dependent Rules bullet and step 2: the API text when an API module is planned,
# a fill-in line otherwise.
_API_RULE = ("- **The document changes only through the API.** Never use Edit or Write on the document "
             "file: the API\n  validates every change before it writes, and `validate` refuses a file "
             "edited by hand.")
_API_STEP = ("2. **Build the document through the API.** Run the heredoc in the API section with the "
             "document name in place\n   of `<name>`. It creates the document on first use and adds one "
             "entry per call.")
_NO_API_RULE = "- TODO(fill): how the document stays consistent without an API, or delete this bullet."
_NO_API_STEP = "2. TODO(fill): how the skill builds its output without an API heredoc."
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

def _contract_path(name: str) -> str:
    """Project-relative contract test path under the first configured test root."""
    roots = active().tests.roots
    if not roots:
        raise StrapError("tests.roots is empty, so the contract test has no root")
    return PurePosixPath(roots[0], "skills", f"test_{snake_case(name)}_skill_contract.py").as_posix()


def scaffold_parts(spec: SkillSpec, project: Optional[Path] = None) -> List[Part]:
    """The parts ``scaffold`` owns for ``spec``, each path project-relative POSIX.

    ``project`` (default: the active project root) is where an edit's models and api modules are looked for.
    """
    root = Path(project) if project is not None else active().project_root
    profile = profile_of(spec)
    parts = [Part(kind=PartKind.SKILL_MD, path=profile.skill_md)]
    if any(behavior.kind == BehaviorKind.MECHANICAL for behavior in spec.behaviors):
        mechanics = [Part(kind=PartKind.MODELS, path=profile.models),
                     Part(kind=PartKind.API, path=profile.api)]
        parts += [part for part in mechanics if _planned_mechanics(spec, part, root)]
    parts.append(Part(kind=PartKind.CONTRACT_TEST, path=_contract_path(spec.name)))
    return parts


def _planned_mechanics(spec: SkillSpec, part: Part, root: Path) -> bool:
    """A new skill gets models and api modules; an edit keeps only those that exist, since its driver may
    already own the mechanics."""
    if SpecMode(spec.mode) == SpecMode.NEW:
        return True
    return (root / part.path).is_file()


def planned_parts(spec: SkillSpec, project: Optional[Path] = None) -> List[Part]:
    """``spec.parts`` as listed, then each scaffold-owned part whose path is not listed yet."""
    parts = list(spec.parts)
    listed = {part.path for part in parts}
    for part in scaffold_parts(spec, project):
        if part.path not in listed:
            parts.append(part)
            listed.add(part.path)
    return parts


# --- rendering ------------------------------------------------------------------------------------------

def _substitutions(spec: SkillSpec, kinds: Set[PartKind]) -> Dict[str, str]:
    values = {"name": spec.name, "snake": snake_case(spec.name), "title": spec.name.replace("-", " ").title(),
              "description": _DESCRIPTION_STUB, "skill_folder": profile_of(spec).skill_folder}
    if profile_of(spec).kind == PROJECT:
        values.update(_project_sections(values, kinds))
    return values


def _project_sections(values: Dict[str, str], kinds: Set[PartKind]) -> Dict[str, str]:
    """The project SKILL.md's API rule, API step, API section and Related bullets: the API text, heredoc and
    module bullets when an API module is planned, fill-in notes otherwise (a prose-only skill names no module
    and states no API rule that does not exist)."""
    if PartKind.API not in kinds:
        return {"api_rule": _NO_API_RULE, "api_step": _NO_API_STEP, "api_section": _NO_API_SECTION,
                "related": "- TODO(fill): the files the skill reads.\n"}
    section = plugin_root().joinpath(*_TEMPLATE_DIR, _PROJECT_API_SECTION).read_text(encoding="utf-8")
    snake = values["snake"]
    related = (f"- `${{CLAUDE_SKILL_DIR}}/scripts/{snake}_api.py`: the API module the heredoc binds.\n"
               f"- `${{CLAUDE_SKILL_DIR}}/scripts/{snake}_models.py`: the document's models.\n")
    return {"api_rule": _API_RULE, "api_step": _API_STEP,
            "api_section": Template(section).substitute(values) + "\n", "related": related}


def _template_text(spec: SkillSpec, kind: PartKind) -> str:
    """The profile's template for ``kind``: the harness set, or the project set under ``project/``."""
    names = _PROJECT_TEMPLATES if profile_of(spec).kind == PROJECT else _TEMPLATES
    return plugin_root().joinpath(*_TEMPLATE_DIR, names[kind]).read_text(encoding="utf-8")


def _targets(spec: SkillSpec, project: Path) -> List[Tuple[PartKind, Path]]:
    """Each planned part that has a template, with its absolute target path."""
    kinds = ((PartKind(part.kind), part.path) for part in planned_parts(spec, project))
    return [(kind, Path(project) / rel) for kind, rel in kinds if kind in _TEMPLATES]


def render_parts(spec: SkillSpec, project: Path) -> List[Path]:
    """Write each templated planned part that is missing; a NEW spec with any target present writes none."""
    targets = _targets(spec, project)
    taken = [path for _kind, path in targets if path.exists()]
    if taken and SpecMode(spec.mode) == SpecMode.NEW:
        listed = ", ".join(path.as_posix() for path in taken)
        raise StrapError(f"{spec.name} is a new skill but these parts exist: {listed}")
    values = _substitutions(spec, {PartKind(part.kind) for part in planned_parts(spec, project)})
    rendered = [(path, Template(_template_text(spec, kind)).substitute(values))
                for kind, path in targets if not path.exists()]
    for path, text in rendered:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return [path for path, _text in rendered]
