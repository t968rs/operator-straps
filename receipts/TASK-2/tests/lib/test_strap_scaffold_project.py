"""Scaffolding a project-profile skill: the parts land in the skill folder and run without harness.

The rendered SKILL.md drives its API through ``harness-skill-api --file``; the rendered models, API and
contract test import no ``harness_lib``, the contract test passes in a project with no harness on
``sys.path``, the API writes its document under the working directory's repository, and the rendered skill
is clean under the project lint once its description is filled.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict

from harness_lib.config import activate, load_config
from harness_lib.strap_api import new_behavior, new_test
from harness_lib.strap_lint import lint_project_skill
from harness_lib.strap_models import SkillSpec, SkillTarget, SpecMode
from harness_lib.strap_scaffold import render_parts

NAME = "demo-skill"
FOLDER = ".claude/skills/demo-skill"
CONTRACT = "tests/skills/test_demo_skill_skill_contract.py"
STUB = "TODO: Use when ..."
MODELS = "demo_skill_models"


def _spec(mechanical: bool = True) -> SkillSpec:
    target = SkillTarget(skills_dir=".claude/skills", agents_dir=".claude/agents")
    spec = SkillSpec(name=NAME, mode=SpecMode.NEW, target=target)
    if not mechanical:
        return spec
    behavior = new_behavior(statement="The document lists each entry once", kind="mechanical",
                            rationale="A file-state fact the API enforces",
                            tests=[new_test("tests/test_demo.py::test_entries", "ImportError")])
    return spec.model_copy(update={"behaviors": [behavior.model_copy(update={"id": "B1"})]})


def _rendered(make_project, mechanical: bool = True) -> Dict[str, Path]:
    root = make_project(config={})
    activate(load_config(root))
    written = render_parts(_spec(mechanical), root)
    return {path.resolve().relative_to(root.resolve()).as_posix(): path for path in written}


def _contract_run(rendered: Dict[str, Path]) -> "subprocess.CompletedProcess[str]":
    """The rendered contract test run by pytest in its project, with no harness on the path."""
    root = rendered[CONTRACT].parents[2]
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", CONTRACT],
                          cwd=str(root), env=env, capture_output=True, text=True)


def _fill_description(skill_md: Path) -> None:
    text = skill_md.read_text(encoding="utf-8")
    assert STUB in text
    skill_md.write_text(text.replace(STUB, "Use when a demo document needs entries."), encoding="utf-8",
                        newline="\n")


def _load(path: Path, alias: str, monkeypatch) -> ModuleType:
    """``path`` loaded as ``alias``; teardown restores ``sys.path`` and the sibling models module entry.

    ``setitem`` records the entry ``sys.modules`` held for ``demo_skill_models`` before the load (or its
    absence), and the ``del`` clears it so the import binds this tmp project's copy; teardown puts the
    recorded state back, so no later test sees a module from a deleted tmp folder.
    """
    monkeypatch.syspath_prepend(str(path.parent))
    monkeypatch.setitem(sys.modules, MODELS, None)
    del sys.modules[MODELS]
    spec = importlib.util.spec_from_file_location(alias, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parts_land_in_the_skill_folder(make_project) -> None:
    assert set(_rendered(make_project)) == {
        f"{FOLDER}/SKILL.md", f"{FOLDER}/scripts/demo_skill_models.py", f"{FOLDER}/scripts/demo_skill_api.py",
        CONTRACT}


def test_skill_md_drives_the_api_through_the_bin_launcher(make_project) -> None:
    text = _rendered(make_project)[f"{FOLDER}/SKILL.md"].read_text(encoding="utf-8")
    assert ('harness-skill-api --repo "${CLAUDE_PROJECT_DIR}" '
            '--file "${CLAUDE_SKILL_DIR}/scripts/demo_skill_api.py"') in text
    assert "${CLAUDE_PLUGIN_ROOT}" not in text


def test_python_parts_import_no_harness_lib(make_project) -> None:
    rendered = _rendered(make_project)
    for rel in (f"{FOLDER}/scripts/demo_skill_models.py", f"{FOLDER}/scripts/demo_skill_api.py", CONTRACT):
        assert "harness_lib" not in rendered[rel].read_text(encoding="utf-8"), rel


def test_rendered_skill_is_clean_under_the_project_lint(make_project) -> None:
    rendered = _rendered(make_project)
    skill_md = rendered[f"{FOLDER}/SKILL.md"]
    _fill_description(skill_md)
    assert lint_project_skill(skill_md.parent, NAME) == []


def test_contract_test_passes_without_harness_on_the_path(make_project) -> None:
    rendered = _rendered(make_project)
    _fill_description(rendered[f"{FOLDER}/SKILL.md"])
    done = _contract_run(rendered)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "skipped" not in done.stdout, done.stdout


def test_prose_only_skill_names_no_missing_module(make_project) -> None:
    rendered = _rendered(make_project, mechanical=False)
    assert set(rendered) == {f"{FOLDER}/SKILL.md", CONTRACT}
    skill_md = rendered[f"{FOLDER}/SKILL.md"]
    _fill_description(skill_md)
    assert "scripts/demo_skill_api.py" not in skill_md.read_text(encoding="utf-8")
    assert lint_project_skill(skill_md.parent, NAME) == []
    done = _contract_run(rendered)
    assert done.returncode == 0, done.stdout + done.stderr


def test_api_writes_under_the_working_directory(make_project, monkeypatch) -> None:
    rendered = _rendered(make_project)
    api = _load(rendered[f"{FOLDER}/scripts/demo_skill_api.py"], "demo_skill_api_under_test", monkeypatch)
    elsewhere = make_project(config={}, name="elsewhere")
    monkeypatch.chdir(elsewhere)
    api.create("alpha")
    path = api.document_path("alpha")
    assert path.is_file()
    assert path.resolve().is_relative_to(elsewhere.resolve()), path
