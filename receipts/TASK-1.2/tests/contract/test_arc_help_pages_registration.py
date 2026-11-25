"""The arc-help-pages skill is named wherever the arc-straps plugin is described.

The plugin manifest, the marketplace entry, the plugin README and the root README's plugin table each say
what arc-straps holds; a skill missing from one of them is a skill a reader of that page never hears of.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _text(repo_root: Path, rel: str) -> str:
    path = repo_root / rel
    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def test_every_description_of_the_plugin_names_the_help_pages_skill(repo_root: Path) -> None:
    manifest = json.loads(_text(repo_root, "plugins/arc-straps/.claude-plugin/plugin.json"))
    plugins = json.loads(_text(repo_root, ".claude-plugin/marketplace.json"))["plugins"]
    entry = next(p for p in plugins if p["name"] == "arc-straps")
    assert "arc-help-pages" in manifest["description"] and "arc-help-pages" in entry["description"]
    assert "`arc-help-pages`" in _text(repo_root, "plugins/arc-straps/README.md")
    rows = re.findall(r"^\|[^|\n]*\|\s*`arc-straps`\s*\|.*$", _text(repo_root, "README.md"), re.MULTILINE)
    assert rows and all("`arc-help-pages`" in row for row in rows), rows
