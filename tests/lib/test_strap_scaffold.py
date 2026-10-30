"""Behavioral tests for harness_lib.strap_scaffold: plugin lookup, the planned parts, and template rendering.

Pins ``find_plugin_dir`` (one manifest name match under the project; ``.git``, ``node_modules``, hidden
directories and linked worktrees, which hold a ``.git`` file, skipped; none or two refused), ``planned_parts``
(``skill_md`` and ``contract_test`` always; ``models`` and ``api`` only with a mechanical behavior; author
parts kept; the contract test under the first configured test root) and ``render_parts`` (real templates
from the shipped plugin; every target checked before any write, so a NEW refusal writes nothing; an EDIT
spec writes only missing parts; ``$title`` and the ``TODO: Use when`` description stub; the rendered
SKILL.md lints with at most the fixed description-prefix message and launches the API through one quoted
``skill_api.py`` heredoc; the rendered API module defines ``__all__``; rendered Python passes
``lint_python`` and compiles). Every project is a throwaway repo built by ``make_project`` and activated
per test.
"""
from __future__ import annotations

import ast
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pytest
from conftest import git

from harness_lib.config import activate, load_config
from harness_lib.project import plugin_root
from harness_lib.strap_api import StrapError
from harness_lib.strap_lint import lint_python, lint_skill
from harness_lib.strap_models import (
    Behavior,
    BehaviorKind,
    JudgmentType,
    Part,
    PartKind,
    PlannedTest,
    RedException,
    SkillSpec,
    SpecMode,
)
from harness_lib.strap_scaffold import find_plugin_dir, planned_parts, render_parts

_NAME = "demo-skill"
_TITLE = "Demo Skill"
_PLUGIN = "plugins/demo"
_MANIFEST = {"name": "demo", "version": "0.1.0"}
_SKILL_MD = f"{_PLUGIN}/skills/{_NAME}/SKILL.md"
_MODELS = f"{_PLUGIN}/lib/harness_lib/demo_skill_models.py"
_API = f"{_PLUGIN}/lib/harness_lib/demo_skill_api.py"
_CONTRACT = "tests/skills/test_demo_skill_skill_contract.py"
# Spelled out so tools/select_tests.py selects this test when a template or the launcher changes.
_TEMPLATES = ("skill_md.tmpl", "models.tmpl", "api.tmpl", "contract_test.tmpl")
_LAUNCHER = ('sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/skill_api.py"'
             " demo_skill_api")
_HEREDOC = re.compile(r"<<-?\s*(['\"])\w+\1")
_PREFIX_PROBLEM = f"{_NAME}: description does not start with 'Use when'"
_PLACEHOLDER = re.compile(r"\$\{?(name|snake|title|description)\b")
_MIRRORED = ("agents", "scripts", "skills", "reference")


@pytest.fixture()
def project(make_project) -> Path:
    """A project holding one plugin named ``demo`` under ``plugins/demo``, activated."""
    root = make_project(config={}, files={f"{_PLUGIN}/.claude-plugin/plugin.json": _MANIFEST})
    activate(load_config(root))
    return root


def _mechanical() -> Behavior:
    test = PlannedTest(node="tests/lib/test_demo.py::test_it", red=RedException.ASSERTION_ERROR)
    return Behavior(id="B1", statement="Writes the file", kind=BehaviorKind.MECHANICAL,
                    rationale="File state shows it", tests=[test])


def _judgment(bid: str = "B2") -> Behavior:
    return Behavior(id=bid, statement="Refuses the shortcut", kind=BehaviorKind.JUDGMENT,
                    type=JudgmentType.TECHNIQUE, rationale="Only the reply shows it")


def _spec(behaviors: List[Behavior], mode: SpecMode = SpecMode.NEW, base: Optional[str] = None,
          parts: Optional[List[Part]] = None) -> SkillSpec:
    return SkillSpec(name=_NAME, mode=mode, base=base, plugin_dir=_PLUGIN, parts=parts or [],
                     behaviors=behaviors)


def _pairs(parts: List[Part]) -> Set[Tuple[str, str]]:
    return {(PartKind(p.kind).value, p.path) for p in parts}


def _planned(spec: SkillSpec) -> SkillSpec:
    """The spec with ``parts`` set to its planned parts, as ``strap.py scaffold`` renders it."""
    return spec.model_copy(update={"parts": planned_parts(spec)})


def _abs(project: Path, path: Path) -> Path:
    return (path if path.is_absolute() else project / path).resolve()


def _manifests(root: Path, layout: Dict[str, str]) -> None:
    for rel, name in layout.items():
        target = root / rel / ".claude-plugin" / "plugin.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"name": "%s"}\n' % name, encoding="utf-8", newline="\n")


def test_find_plugin_dir_returns_the_matching_manifest(make_project) -> None:
    root = make_project(config={})
    _manifests(root, {"plugins/demo": "demo", "plugins/other": "other"})
    assert _abs(root, find_plugin_dir(root, "demo")) == (root / "plugins/demo").resolve()


def test_find_plugin_dir_skips_node_modules(make_project) -> None:
    root = make_project(config={})
    _manifests(root, {"plugins/demo": "demo", "node_modules/pkg": "demo"})
    assert _abs(root, find_plugin_dir(root, "demo")) == (root / "plugins/demo").resolve()


@pytest.mark.parametrize("hidden", [".claude/worktrees/x", ".worktrees/x"], ids=["claude", "dot"])
def test_find_plugin_dir_skips_hidden_dirs(make_project, hidden: str) -> None:
    root = make_project(config={})
    _manifests(root, {"plugins/demo": "demo", f"{hidden}/plugins/demo": "demo"})
    assert _abs(root, find_plugin_dir(root, "demo")) == (root / "plugins/demo").resolve()


def test_find_plugin_dir_skips_linked_worktrees(make_project) -> None:
    """A directory holding a ``.git`` file is a linked worktree; its mirrored manifest does not count."""
    root = make_project(config={})
    _manifests(root, {"plugins/demo": "demo", "mirror/plugins/demo": "demo"})
    (root / "mirror" / ".git").write_text("gitdir: elsewhere/.git/worktrees/mirror\n", encoding="utf-8",
                                          newline="\n")
    assert _abs(root, find_plugin_dir(root, "demo")) == (root / "plugins/demo").resolve()


def test_find_plugin_dir_refuses_no_match(make_project) -> None:
    root = make_project(config={})
    _manifests(root, {"plugins/other": "other"})
    with pytest.raises(StrapError):
        find_plugin_dir(root, "demo")


def test_find_plugin_dir_refuses_two_matches(make_project) -> None:
    root = make_project(config={})
    _manifests(root, {"plugins/a": "demo", "plugins/b": "demo"})
    with pytest.raises(StrapError):
        find_plugin_dir(root, "demo")


def test_planned_parts_judgment_only_minimal(project: Path) -> None:
    parts = planned_parts(_spec([_judgment()]))
    assert _pairs(parts) == {("skill_md", _SKILL_MD), ("contract_test", _CONTRACT)}


def test_planned_parts_mechanical_adds_models_and_api(project: Path) -> None:
    parts = planned_parts(_spec([_mechanical(), _judgment()]))
    expected = {("skill_md", _SKILL_MD), ("contract_test", _CONTRACT), ("models", _MODELS), ("api", _API)}
    assert _pairs(parts) == expected


def test_planned_parts_keeps_author_parts(project: Path) -> None:
    driver = Part(kind=PartKind.DRIVER, path=f"{_PLUGIN}/scripts/demo_skill.py")
    agent = Part(kind=PartKind.AGENT, path=f"{_PLUGIN}/agents/demo-runner.md")
    pairs = _pairs(planned_parts(_spec([_judgment()], parts=[driver, agent])))
    assert ("driver", driver.path) in pairs
    assert ("agent", agent.path) in pairs


def test_planned_parts_lists_a_present_part_once(project: Path) -> None:
    existing = Part(kind=PartKind.SKILL_MD, path=_SKILL_MD)
    paths = [p.path for p in planned_parts(_spec([_judgment()], parts=[existing]))]
    assert paths.count(_SKILL_MD) == 1
    assert len(paths) == len(set(paths))


def test_planned_parts_contract_under_first_root(make_project) -> None:
    root = make_project(config={"tests": {"roots": ["qa/", "tests/"]}})
    activate(load_config(root))
    pairs = _pairs(planned_parts(_spec([_judgment()])))
    assert ("contract_test", "qa/skills/test_demo_skill_skill_contract.py") in pairs


def test_templates_ship_with_the_plugin() -> None:
    folder = plugin_root() / "skills" / "strap-skills" / "templates"
    missing = [t for t in _TEMPLATES if not (folder / t).is_file()]
    assert not missing, f"templates missing under {folder}: {missing}"


def test_render_parts_new_writes_every_planned_part(project: Path) -> None:
    spec = _planned(_spec([_mechanical(), _judgment()]))
    written = {_abs(project, p) for p in render_parts(spec, project)}
    assert written == {(project / p.path).resolve() for p in spec.parts}
    assert all(path.is_file() for path in written)


@pytest.mark.parametrize("taken_rel", [_SKILL_MD, _API, _CONTRACT], ids=["skill_md", "api", "contract"])
def test_render_parts_new_refusal_writes_nothing(project: Path, taken_rel: str) -> None:
    """A NEW spec with any target present is refused before any write, whatever the write order."""
    taken = project / taken_rel
    taken.parent.mkdir(parents=True, exist_ok=True)
    taken.write_text("# taken\n", encoding="utf-8", newline="\n")
    spec = _planned(_spec([_mechanical(), _judgment()]))
    with pytest.raises(StrapError):
        render_parts(spec, project)
    assert taken.read_text(encoding="utf-8") == "# taken\n"
    others = [p.path for p in spec.parts if p.path != taken_rel and (project / p.path).exists()]
    assert not others, others


def test_render_parts_edit_writes_only_missing_parts(project: Path) -> None:
    skill = project / _SKILL_MD
    skill.parent.mkdir(parents=True)
    skill.write_text("original\n", encoding="utf-8", newline="\n")
    spec = _planned(_spec([_mechanical()], mode=SpecMode.EDIT, base=git(project, "rev-parse", "HEAD")))
    written = {_abs(project, p) for p in render_parts(spec, project)}
    assert skill.read_text(encoding="utf-8") == "original\n"
    assert skill.resolve() not in written
    assert written == {(project / rel).resolve() for rel in (_MODELS, _API, _CONTRACT)}


def _mirror_shipped_plugin(project: Path) -> None:
    """Copy the shipped plugin's agents, scripts, skills and reference into ``plugins/demo``, so the
    rendered skill resolves the same plugin paths it would in the shipped plugin."""
    for folder in _MIRRORED:
        source = plugin_root() / folder
        if source.is_dir():
            shutil.copytree(source, project / _PLUGIN / folder, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))


def _rendered(project: Path) -> List[Path]:
    paths = render_parts(_planned(_spec([_mechanical(), _judgment()])), project)
    return [_abs(project, p) for p in paths]


def _frontmatter(text: str) -> Dict[str, str]:
    """Top-level ``key: value`` pairs of the leading ``---`` block, one matching quote pair stripped."""
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", "SKILL.md does not open with frontmatter"
    keys: Dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return keys
        match = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", line)
        if match:
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            keys[match.group(1)] = value
    raise AssertionError("SKILL.md frontmatter is not closed")


def _fenced_lines(text: str) -> List[str]:
    """Lines inside triple-backtick fences, fence markers excluded."""
    inside, found = False, []
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside:
            found.append(line)
    return found


def test_rendered_skill_md_description_stub(project: Path) -> None:
    _rendered(project)
    keys = _frontmatter((project / _SKILL_MD).read_text(encoding="utf-8"))
    assert keys.get("name") == _NAME, keys
    assert keys.get("description", "").startswith("TODO: Use when"), keys


def test_rendered_files_carry_the_title(project: Path) -> None:
    texts = [path.read_text(encoding="utf-8") for path in _rendered(project)]
    assert any(_TITLE in text for text in texts), f"{_TITLE!r} rendered nowhere"


def test_rendered_skill_md_lints_to_prefix_only(project: Path) -> None:
    _mirror_shipped_plugin(project)
    _rendered(project)
    problems = lint_skill(project / _PLUGIN, _NAME)
    assert problems in ([], [_PREFIX_PROBLEM]), problems


def test_rendered_skill_md_launches_skill_api(project: Path) -> None:
    _rendered(project)
    fenced = _fenced_lines((project / _SKILL_MD).read_text(encoding="utf-8"))
    launcher = re.compile(re.escape(_LAUNCHER) + r"(\s|$)")
    launches = [line for line in fenced if launcher.search(line)]
    assert len(launches) == 1, launches
    assert _HEREDOC.search(launches[0]), f"no quoted heredoc opener: {launches[0]}"


def test_rendered_api_module_defines_all(project: Path) -> None:
    _rendered(project)
    tree = ast.parse((project / _API).read_text(encoding="utf-8"))
    values = [node.value for node in tree.body
              if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
              and any(isinstance(t, ast.Name) and t.id == "__all__"
                      for t in (node.targets if isinstance(node, ast.Assign) else [node.target]))]
    assert len(values) == 1, "rendered API module does not assign __all__ once at module level"
    assert isinstance(values[0], (ast.List, ast.Tuple)), ast.dump(values[0])
    assert all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in values[0].elts)


def test_rendered_python_passes_lint_python(project: Path) -> None:
    py_files = [p for p in _rendered(project) if p.suffix == ".py"]
    assert len(py_files) == 3, py_files
    problems = {str(p): lint_python(p) for p in py_files}
    assert all(not found for found in problems.values()), problems


def test_rendered_python_compiles(project: Path) -> None:
    py_files = [p for p in _rendered(project) if p.suffix == ".py"]
    assert len(py_files) == 3, py_files
    for path in py_files:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_rendered_files_carry_no_template_placeholder(project: Path) -> None:
    left = {}
    for path in _rendered(project):
        found = _PLACEHOLDER.findall(path.read_text(encoding="utf-8"))
        if found:
            left[str(path)] = found
    assert not left, left
