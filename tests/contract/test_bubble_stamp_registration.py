"""The bubble-stamp mod is registered where every mod is.

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
    entry = next((p for p in plugins if p["name"] == "bubble-stamp"), None)
    assert entry is not None and entry["source"] == "./plugins/bubble-stamp"


def test_the_mod_manifest_and_hooks(repo_root: Path) -> None:
    manifest = json.loads(_text(repo_root, "plugins/bubble-stamp/.claude-plugin/plugin.json"))
    assert manifest["name"] == "bubble-stamp" and manifest["version"] == "0.1.0"
    hooks = json.loads(_text(repo_root, "plugins/bubble-stamp/hooks/hooks.json"))
    assert hooks == {"modules": ["./register.ts"]}


def test_ci_runs_the_mod_tests(repo_root: Path) -> None:
    assert "plugins/bubble-stamp" in _text(repo_root, ".github/workflows/ci.yml")


def test_the_readme_documents_and_installs_the_mod(repo_root: Path) -> None:
    readme = _text(repo_root, "README.md")
    assert "claude plugin install bubble-stamp@operator-straps" in readme
    assert re.search(r"\|[^|\n]*\|\s*`bubble-stamp`\s*\|", readme)
    assert "bubble-memo" in readme


def test_claude_md_counts_six_mods(repo_root: Path) -> None:
    text = _text(repo_root, "CLAUDE.md")
    assert "six TypeScript mods" in text and "`bubble-stamp`" in text


def test_the_harness_version_moved_past_the_old_one(repo_root: Path) -> None:
    assert _version(_text(repo_root, "plugins/harness/.claude-plugin/plugin.json")) > (0, 39, 1)


def test_pr_review_watch_moved_past_its_old_version(repo_root: Path) -> None:
    assert _version(_text(repo_root, "plugins/pr-review-watch/.claude-plugin/plugin.json")) > (0, 4, 1)


def test_the_mod_has_a_readme(repo_root: Path) -> None:
    assert "bubble-stamp" in _text(repo_root, "plugins/bubble-stamp/README.md")


@pytest.mark.parametrize("rel", [
    pytest.param("plugins/bubble-stamp/tsconfig.json", id="tsconfig"),
    pytest.param("plugins/bubble-stamp/.gitignore", id="gitignore"),
])
def test_engine_scaffolding(repo_root: Path, rel: str) -> None:
    assert (repo_root / rel).is_file()
