"""The working-refs mod is registered where every mod is.

Marketplace, CI, README and its own manifest and scaffolding.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


def _text(repo_root: Path, rel: str) -> str:
    path = repo_root / rel
    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def test_the_marketplace_lists_the_mod(repo_root: Path) -> None:
    plugins = json.loads(_text(repo_root, ".claude-plugin/marketplace.json"))["plugins"]
    entry = next((p for p in plugins if p["name"] == "working-refs"), None)
    assert entry is not None and entry["source"] == "./plugins/working-refs"


def test_the_mod_manifest_and_hooks(repo_root: Path) -> None:
    manifest = json.loads(_text(repo_root, "plugins/working-refs/.claude-plugin/plugin.json"))
    assert manifest["name"] == "working-refs"
    assert manifest["types"] == "./types/index.d.ts"
    assert "git-status" in manifest["dependencies"]
    hooks = json.loads(_text(repo_root, "plugins/working-refs/hooks/hooks.json"))
    assert hooks == {"modules": ["./register.ts"]}


def test_ci_runs_the_mod_tests(repo_root: Path) -> None:
    ci = _text(repo_root, ".github/workflows/ci.yml")
    assert re.search(r"for p in [^;]*plugins/working-refs[^;]*; do claude plugin test", ci)


def test_the_readme_documents_and_installs_the_mod(repo_root: Path) -> None:
    readme = _text(repo_root, "README.md")
    assert "claude plugin install working-refs@operator-straps" in readme
    assert re.search(r"\|[^|\n]*\|\s*`working-refs`\s*\|", readme)


@pytest.mark.parametrize("rel", [
    pytest.param("plugins/working-refs/tsconfig.json", id="tsconfig"),
    pytest.param("plugins/working-refs/.gitignore", id="gitignore"),
    pytest.param("plugins/working-refs/types/index.d.ts", id="types"),
])
def test_engine_scaffolding(repo_root: Path, rel: str) -> None:
    assert (repo_root / rel).is_file()
