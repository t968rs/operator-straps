"""The parallel2-lanes mod is registered where every mod is.

Marketplace, CI, README, CLAUDE.md and its own manifest.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Tuple

import pytest


def _text(repo_root: Path, rel: str) -> str:
    path = repo_root / rel
    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def _version(text: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in json.loads(text)["version"].split("."))


def test_the_marketplace_lists_the_mod(repo_root: Path) -> None:
    plugins = json.loads(_text(repo_root, ".claude-plugin/marketplace.json"))["plugins"]
    entry = next((p for p in plugins if p["name"] == "parallel2-lanes"), None)
    assert entry is not None and entry["source"] == "./plugins/parallel2-lanes"


def test_the_mod_manifest_and_hooks(repo_root: Path) -> None:
    manifest = json.loads(_text(repo_root, "plugins/parallel2-lanes/.claude-plugin/plugin.json"))
    assert manifest["name"] == "parallel2-lanes"
    assert manifest["types"] == "./types/index.d.ts"
    assert _version(json.dumps(manifest)) >= (0, 1, 0)
    hooks = json.loads(_text(repo_root, "plugins/parallel2-lanes/hooks/hooks.json"))
    assert hooks == {"modules": ["./register.ts"]}


def test_ci_runs_the_mod_tests(repo_root: Path) -> None:
    assert "plugins/parallel2-lanes" in _text(repo_root, ".github/workflows/ci.yml")


def test_the_readme_documents_and_installs_the_mod(repo_root: Path) -> None:
    readme = _text(repo_root, "README.md")
    assert "claude plugin install parallel2-lanes@operator-straps" in readme
    assert re.search(r"\|[^|\n]*\|\s*`parallel2-lanes`\s*\|", readme)


def test_claude_md_names_the_mod(repo_root: Path) -> None:
    assert "`parallel2-lanes`" in _text(repo_root, "CLAUDE.md")


def test_the_mod_has_a_readme(repo_root: Path) -> None:
    assert "parallel2-lanes" in _text(repo_root, "plugins/parallel2-lanes/README.md")


def test_the_harness_skill_names_the_mod(repo_root: Path) -> None:
    assert "parallel2-lanes" in _text(repo_root, "plugins/harness/skills/parallel2/SKILL.md")


@pytest.mark.parametrize("rel", [
    pytest.param("plugins/parallel2-lanes/tsconfig.json", id="tsconfig"),
    pytest.param("plugins/parallel2-lanes/.gitignore", id="gitignore"),
    pytest.param("plugins/parallel2-lanes/types/index.d.ts", id="types"),
])
def test_engine_scaffolding(repo_root: Path, rel: str) -> None:
    assert (repo_root / rel).is_file()
