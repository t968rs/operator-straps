"""The arc-straps plugin is registered where every plugin is, and declares its harness dependency.

The release notes carry the manifest's version in an arc-straps row, and the manifest and the marketplace
describe the plugin in the same words, so each pull request that bumps the plugin keeps both in step.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

WALK_ROOTS = ("docs/RELEASES/",)


def _text(repo_root: Path, rel: str) -> str:
    path = repo_root / rel
    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def test_the_marketplace_lists_the_plugin(repo_root: Path) -> None:
    plugins = json.loads(_text(repo_root, ".claude-plugin/marketplace.json"))["plugins"]
    entry = next((p for p in plugins if p["name"] == "arc-straps"), None)
    assert entry is not None and entry["source"] == "./plugins/arc-straps"


def test_the_manifest_depends_on_harness(repo_root: Path) -> None:
    manifest = json.loads(_text(repo_root, "plugins/arc-straps/.claude-plugin/plugin.json"))
    assert manifest["name"] == "arc-straps"
    assert manifest["dependencies"] == [{"name": "harness", "version": ">=0.56.0"}]


def test_the_readme_documents_and_installs_the_plugin(repo_root: Path) -> None:
    readme = _text(repo_root, "README.md")
    assert "claude plugin install arc-straps@operator-straps" in readme
    assert re.search(r"\|[^|\n]*\|\s*`arc-straps`\s*\|", readme)
    assert re.search(r"^\|\s*`plugins`\s*\|", readme, re.MULTILINE)


def test_claude_md_names_the_plugin(repo_root: Path) -> None:
    assert "`arc-straps`" in _text(repo_root, "CLAUDE.md")


def test_the_plugin_readme_documents_its_keys(repo_root: Path) -> None:
    text = _text(repo_root, "plugins/arc-straps/README.md")
    schema = json.loads(_text(repo_root, "plugins/arc-straps/config/arc-straps.schema.json"))
    keys = list(schema["properties"]["arc_meta"]["properties"])
    assert keys, "the schema lists no arc_meta keys"
    for key in [*keys, "harness-skill-api"]:
        assert f"`{key}`" in text, key


def test_provenance_records_the_port(repo_root: Path) -> None:
    text = _text(repo_root, "docs/PROVENANCE.md")
    assert "plugins/arc-straps/skills/arc-meta/" in text and "0c4e45eb6" in text


def _manifest(repo_root: Path) -> dict:
    return json.loads(_text(repo_root, "plugins/arc-straps/.claude-plugin/plugin.json"))


def _release_rows(repo_root: Path) -> List[str]:
    """Every arc-straps row of the release-notes tables under docs/RELEASES/."""
    rows: List[str] = []
    for path in sorted((repo_root / "docs" / "RELEASES").glob("v*.md")):
        rows += re.findall(r"^\|\s*arc-straps\s*\|.*$", path.read_text(encoding="utf-8"), re.MULTILINE)
    return rows


def test_the_release_notes_carry_the_manifest_version(repo_root: Path) -> None:
    version = re.escape(_manifest(repo_root)["version"])
    rows = _release_rows(repo_root)
    assert any(re.search(rf"\|\s*{version}\s*\|\s*$", row) for row in rows), rows


def test_the_manifest_and_the_marketplace_describe_the_plugin_alike(repo_root: Path) -> None:
    plugins = json.loads(_text(repo_root, ".claude-plugin/marketplace.json"))["plugins"]
    entry = next(p for p in plugins if p["name"] == "arc-straps")
    assert entry["description"] == _manifest(repo_root)["description"]


def test_the_plugin_readme_says_links_pass_through(repo_root: Path) -> None:
    """The README's account of arc-meta says ``<a href>`` reaches the "?" page."""
    text = _text(repo_root, "plugins/arc-straps/README.md")
    what = text.partition("## What it is")[2].partition("\n## ")[0]
    assert "`<a href>`" in what, what
