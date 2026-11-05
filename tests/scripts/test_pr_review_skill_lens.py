"""Behavioral test of the pr-review driver's per-skill-package trigger over any ``skills/`` folder.

The driver asks git which candidate folders hold a ``SKILL.md`` at the PR head and greps the skill's name
there; a ``skills/`` folder without one (a domain folder that happens to be called ``skills``) never
triggers, and the project's ``skills_dir`` does not limit where a skill may live.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterator, Sequence

import pytest

from conftest import git
from harness_lib.config import activate, load_config
from harness_lib.pr_summary import PrFacts, PrFile

_SCRIPT = Path("scripts") / "pr_review.py"
_FILES = {
    "plugins/p/skills/demo/SKILL.md": "---\nname: demo\n---\n",
    "plugins/p/skills/demo/ref.md": "reference\n",
    "src/skills/fake/x.py": "X = 1\n",
    "docs/guide.md": "Run demo first, then fake.\n",
}


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> Iterator[ModuleType]:
    """Import pr_review.py by absolute path, registered in ``sys.modules`` so annotations resolve."""
    spec = importlib.util.spec_from_file_location("pr_review_skill_lens_under_test", plugin_root / _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _facts(head: str, paths: Sequence[str]) -> PrFacts:
    """PR facts at ``head`` modifying ``paths``."""
    return PrFacts(1, "demo", "1-demo", "main", head, head, "", (),
                   tuple(PrFile("M", p, None, 1, 0) for p in paths))


def test_any_skills_folder_with_skill_md_triggers(script: ModuleType, make_project) -> None:
    root = make_project(config={"exclusions": None, "skills_dir": ".claude/skills/"}, files=_FILES)
    activate(load_config(root))
    head = git(root, "rev-parse", "HEAD")
    paths = ("plugins/p/skills/demo/ref.md", "src/skills/fake/x.py")
    catalog = {"lenses": [], "default_sub_lenses": []}
    lenses, skills = script.lens_paths(root, _facts(head, paths), paths, (), catalog)
    assert skills == ("demo",)
    assert lenses.get("per-skill-package") == ("plugins/p/skills/demo/ref.md",)
